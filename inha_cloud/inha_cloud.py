"""Conservative CLOUDHUB form client, not an official SSO or enrollment verifier."""

from dataclasses import dataclass, field
from enum import Enum
import math
from numbers import Real
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import requests

_BASE_URL = "https://cloud.inha.ac.kr"
_LOGIN_URL = _BASE_URL + "/auth/login"
_MAX_REDIRECTS = 5
_MAX_BODY_BYTES = 1024 * 1024
_HIDDEN_FIELDS = frozenset({"_csrf", "loginDomain", "SAMLRequest", "RelayState", "requestId", "referer"})


class LoginStatus(str, Enum):
    SUCCESS = "success"
    REJECTED = "rejected"
    ADDITIONAL_AUTH = "additional_auth"
    PAGE_CHANGED = "page_changed"
    NETWORK_ERROR = "network_error"
    INVALID_INPUT = "invalid_input"
    UNSAFE_DESTINATION = "unsafe_destination"
    IDENTITY_MISMATCH = "identity_mismatch"
    RATE_LIMITED = "rate_limited"
    SERVICE_UNAVAILABLE = "service_unavailable"
    HTTP_ERROR = "http_error"
    NOT_AUTHENTICATED = "not_authenticated"
    CLOSED = "closed"


_MESSAGES = {
    LoginStatus.SUCCESS: "요청한 계정과 일치하는 로그인 화면 정보를 확인했습니다.",
    LoginStatus.REJECTED: "인증이 완료되지 않았습니다. 비밀번호 오류를 확정하는 결과는 아닙니다.",
    LoginStatus.ADDITIONAL_AUTH: "학교 사이트의 추가 인증이 필요합니다. 자동 제출하지 않았습니다.",
    LoginStatus.PAGE_CHANGED: "기대한 로그인 화면이나 계정 정보를 확인하지 못했습니다.",
    LoginStatus.NETWORK_ERROR: "학교 요청 중 연결 오류가 발생했습니다. 인증 결과는 불확실하며 자동 재시도하지 않습니다.",
    LoginStatus.INVALID_INPUT: "학교 계정 아이디와 비밀번호 입력을 확인하세요.",
    LoginStatus.UNSAFE_DESTINATION: "허용되지 않은 인증 목적지 또는 자격 증명 재전송을 차단했습니다.",
    LoginStatus.IDENTITY_MISMATCH: "응답 계정이 요청한 계정과 일치하지 않아 인증을 인정하지 않았습니다.",
    LoginStatus.RATE_LIMITED: "학교 서버가 요청을 제한했습니다. 자동 재시도하지 않습니다.",
    LoginStatus.SERVICE_UNAVAILABLE: "학교 서비스 오류로 인증 결과를 확인할 수 없습니다.",
    LoginStatus.HTTP_ERROR: "예상하지 못한 HTTP 응답으로 인증 결과를 확인할 수 없습니다.",
    LoginStatus.NOT_AUTHENTICATED: "이 클라이언트에서 확인된 로그인 세션이 없습니다.",
    LoginStatus.CLOSED: "종료된 클라이언트입니다. 새 클라이언트를 사용하세요.",
}


@dataclass(frozen=True)
class Identity:
    """Observed account id and display text; neither enrollment nor a verified legal name."""

    account_id: str = field(repr=False)
    display_name: str = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.account_id, str) or not self.account_id.strip():
            raise ValueError("계정 ID가 비어 있습니다.")
        if not isinstance(self.display_name, str):
            raise ValueError("표시 문구는 문자열이어야 합니다.")


@dataclass(frozen=True)
class LoginResult:
    """Immutable observation; retained success is not proof of a still-live session."""

    status: LoginStatus
    identity: Identity | None = field(default=None, repr=False)
    http_status: int | None = None

    def __post_init__(self):
        if not isinstance(self.status, LoginStatus):
            raise TypeError("LoginStatus 값이 필요합니다.")
        if (self.status is LoginStatus.SUCCESS) != isinstance(self.identity, Identity):
            raise ValueError("성공 결과에만 Identity가 필요합니다.")
        if self.identity is not None and self.status is not LoginStatus.SUCCESS:
            raise ValueError("실패 결과에는 Identity를 포함할 수 없습니다.")
        if self.http_status is not None and (
            type(self.http_status) is not int or not 100 <= self.http_status <= 599
        ):
            raise ValueError("HTTP 상태 코드가 올바르지 않습니다.")

    @property
    def success(self) -> bool:
        return self.status is LoginStatus.SUCCESS

    @property
    def message(self) -> str:
        return _MESSAGES[self.status]

    def __bool__(self):
        raise TypeError("LoginResult.success로 성공 여부를 확인하세요.")


class _FlowFailure(Exception):
    def __init__(self, status: LoginStatus, http_status: int | None = None):
        self.status = status
        self.http_status = http_status
        super().__init__(status.value)


@dataclass(frozen=True)
class _Page:
    url: str
    status: int
    text: str = field(repr=False)


def _scoped(url: str) -> str:
    try:
        parsed = urlsplit(url)
        allowed = (
            parsed.scheme == "https"
            and parsed.hostname == "cloud.inha.ac.kr"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and not any(c in url for c in ("\r", "\n", "\\"))
        )
    except ValueError:
        allowed = False
    if not allowed:
        raise _FlowFailure(LoginStatus.UNSAFE_DESTINATION)
    return url


def _mfa_url(url: str) -> bool:
    prepared = requests.PreparedRequest()
    try:
        prepared.prepare_url(url, None)
    except requests.RequestException:
        raise _FlowFailure(LoginStatus.UNSAFE_DESTINATION) from None
    path = urlsplit(prepared.url).path.lower().rstrip("/")
    return path == "/auth/mfa" or path.startswith("/auth/mfa/")


def _mfa(page: _Page, soup: BeautifulSoup) -> bool:
    if _mfa_url(page.url):
        return True
    if soup.select_one('input[name="pincode"], input[name="pin1"], input[name="otpCode"], input[name="otpToken"], #otpCode, #otpToken'):
        return True
    for form in soup.select("form[action]"):
        try:
            is_mfa = _mfa_url(urljoin(page.url, form["action"]))
        except ValueError:
            continue
        if is_mfa:
            return True
    return False


class _Session(requests.Session):
    def resolve_redirects(self, *args, **kwargs):
        # requests otherwise consumes redirect bodies and prepares Response.next even
        # with allow_redirects=False. All navigation belongs to _request instead.
        return iter(())


class InhaCloud:
    """Owns one user's transient session. Do not share an instance between threads/users.

    Environment credentials, proxies, netrc and dotenv are not read here. POST credentials
    are never retried or replayed through 307/308. close() only closes the local session.
    """

    def __init__(self, *, timeout: float = 15):
        if isinstance(timeout, bool) or not isinstance(timeout, Real):
            raise ValueError("요청 제한 시간은 유한한 양수여야 합니다.")
        try:
            self._timeout = float(timeout)
        except OverflowError:
            raise ValueError("요청 제한 시간은 유한한 양수여야 합니다.") from None
        if not math.isfinite(self._timeout) or self._timeout <= 0:
            raise ValueError("요청 제한 시간은 유한한 양수여야 합니다.")
        self._session: requests.Session | None = None
        self._account: str | None = None
        self._closed = False

    def _clear_session(self):
        self._account = None
        session, self._session = self._session, None
        if session is not None:
            try:
                session.cookies.clear()
            finally:
                session.close()

    def _finish(self, result: LoginResult) -> LoginResult:
        if not result.success:
            self._clear_session()
        return result

    def _request(self, method: str, url: str, data=None) -> _Page:
        """Manual same-origin redirects, bounded HTML, no retries or ambient credentials."""
        if self._session is None:
            raise _FlowFailure(LoginStatus.NOT_AUTHENTICATED)
        for redirect_count in range(_MAX_REDIRECTS + 1):
            _scoped(url)
            if method == "POST" and url != _LOGIN_URL:
                raise _FlowFailure(LoginStatus.UNSAFE_DESTINATION)
            try:
                response = self._session.request(
                    method, url, data=data, timeout=(min(5.0, self._timeout), self._timeout),
                    allow_redirects=False, stream=True,
                )
                try:
                    _scoped(response.url)
                    status = response.status_code
                    if not 100 <= status <= 599:
                        raise _FlowFailure(LoginStatus.HTTP_ERROR)
                    if status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location or redirect_count == _MAX_REDIRECTS:
                            raise _FlowFailure(LoginStatus.PAGE_CHANGED, status)
                        target = _scoped(urljoin(url, location))
                        if method == "POST" and status in (307, 308):
                            raise _FlowFailure(LoginStatus.UNSAFE_DESTINATION, status)
                        if _mfa_url(target):
                            raise _FlowFailure(LoginStatus.ADDITIONAL_AUTH, status)
                        if status == 303 or (method == "POST" and status in (301, 302)):
                            method, data = "GET", None
                        url = target
                        continue
                    if status == 429:
                        raise _FlowFailure(LoginStatus.RATE_LIMITED, status)
                    if 500 <= status <= 599:
                        raise _FlowFailure(LoginStatus.SERVICE_UNAVAILABLE, status)
                    if status in (401, 403):
                        raise _FlowFailure(LoginStatus.REJECTED, status)
                    if not 200 <= status <= 299:
                        raise _FlowFailure(LoginStatus.HTTP_ERROR, status)
                    chunks, size = [], 0
                    for chunk in response.iter_content(16384):
                        size += len(chunk)
                        if size > _MAX_BODY_BYTES:
                            raise _FlowFailure(LoginStatus.PAGE_CHANGED, status)
                        chunks.append(chunk)
                    encoding = response.encoding
                    if not encoding or encoding.lower() == "iso-8859-1":
                        encoding = "utf-8"
                    try:
                        text = b"".join(chunks).decode(encoding, errors="replace")
                    except LookupError:
                        raise _FlowFailure(LoginStatus.PAGE_CHANGED, status) from None
                    media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                    if text.strip() and media_type not in ("text/html", "application/xhtml+xml"):
                        raise _FlowFailure(LoginStatus.PAGE_CHANGED, status)
                    return _Page(response.url, status, text)
                finally:
                    response.close()
            except requests.RequestException:
                raise _FlowFailure(LoginStatus.NETWORK_ERROR) from None
            except ValueError:
                raise _FlowFailure(LoginStatus.UNSAFE_DESTINATION) from None
        raise _FlowFailure(LoginStatus.PAGE_CHANGED)

    def _login_payload(self, page: _Page) -> dict[str, str]:
        if page.status != 200:
            raise _FlowFailure(LoginStatus.PAGE_CHANGED, page.status)
        soup = BeautifulSoup(page.text, "html.parser")
        if _mfa(page, soup):
            raise _FlowFailure(LoginStatus.ADDITIONAL_AUTH, page.status)
        candidates = []
        for form in soup.select("form[action]"):
            try:
                target = urljoin(page.url, form["action"])
                path = urlsplit(target).path
            except ValueError:
                raise _FlowFailure(LoginStatus.PAGE_CHANGED, page.status) from None
            if form.select_one('input[type="password"]') or path == "/auth/login":
                _scoped(target)
            if path == "/auth/login":
                candidates.append((form, target))
        if len(candidates) != 1:
            raise _FlowFailure(LoginStatus.PAGE_CHANGED, page.status)
        form, target = candidates[0]
        if target != _LOGIN_URL:
            raise _FlowFailure(LoginStatus.UNSAFE_DESTINATION, page.status)
        if form.get("method", "GET").upper() != "POST":
            raise _FlowFailure(LoginStatus.PAGE_CHANGED, page.status)
        for name in ("_csrf", "loginDomain", "userid", "password"):
            fields = form.select(f'input[name="{name}"]')
            if len(fields) != 1 or fields[0].has_attr("disabled"):
                raise _FlowFailure(LoginStatus.PAGE_CHANGED, page.status)
        if not form.select_one('input[name="password"][type="password"]'):
            raise _FlowFailure(LoginStatus.PAGE_CHANGED, page.status)
        payload = {}
        for item in form.select('input[type="hidden"][name]'):
            name = item["name"]
            if name in _HIDDEN_FIELDS:
                if name in payload:
                    raise _FlowFailure(LoginStatus.PAGE_CHANGED, page.status)
                payload[name] = item.get("value", "")
        if not payload.get("_csrf", "").strip() or payload.get("loginDomain") != "inha.ac.kr":
            raise _FlowFailure(LoginStatus.PAGE_CHANGED, page.status)
        return payload

    def _read_identity(self, page: _Page, account: str) -> LoginResult:
        if page.status != 200:
            return LoginResult(LoginStatus.PAGE_CHANGED, http_status=page.status)
        soup = BeautifulSoup(page.text, "html.parser")
        if _mfa(page, soup):
            return LoginResult(LoginStatus.ADDITIONAL_AUTH, http_status=page.status)
        login_form = False
        for form in soup.select("form[action]"):
            try:
                if urlsplit(urljoin(page.url, form["action"])).path == "/auth/login":
                    login_form = True
            except ValueError:
                return LoginResult(LoginStatus.PAGE_CHANGED, http_status=page.status)
        if login_form or soup.select_one('input[type="password"]'):
            return LoginResult(LoginStatus.REJECTED, http_status=page.status)
        headers = soup.select(".loginHeader[data-userid]")
        if len(headers) != 1:
            return LoginResult(LoginStatus.PAGE_CHANGED, http_status=page.status)
        account_id = str(headers[0].get("data-userid", "")).strip()
        if not account_id:
            return LoginResult(LoginStatus.PAGE_CHANGED, http_status=page.status)
        if account_id != account:
            return LoginResult(LoginStatus.IDENTITY_MISMATCH, http_status=page.status)
        return LoginResult(LoginStatus.SUCCESS, Identity(account_id, headers[0].get_text(" ", strip=True)), page.status)

    def login(self, username: str, password: str) -> LoginResult:
        """One authentication attempt; no secret is retained on this client or its result."""
        if self._closed:
            return LoginResult(LoginStatus.CLOSED)
        self._clear_session()
        if not isinstance(username, str) or not username.strip() or not isinstance(password, str) or not password:
            return LoginResult(LoginStatus.INVALID_INPUT)
        account = username.strip()
        payload = {}
        try:
            self._session = _Session()
            self._session.trust_env = False
            page = self._request("GET", _BASE_URL)
            payload = self._login_payload(page)
            payload.update(userid=account, password=password)
            page = self._request("POST", _LOGIN_URL, payload)
            if page.status == 204 or (page.status == 200 and not page.text.strip()):
                if _mfa(page, BeautifulSoup(page.text, "html.parser")):
                    raise _FlowFailure(LoginStatus.ADDITIONAL_AUTH, page.status)
                page = self._request("GET", _BASE_URL)
            result = self._read_identity(page, account)
            if result.success:
                self._account = account
            return self._finish(result)
        except _FlowFailure as failure:
            return self._finish(LoginResult(failure.status, http_status=failure.http_status))
        except BaseException:
            self._clear_session()
            raise
        finally:
            payload.clear()
            password = None

    def fetch_login_info(self) -> LoginResult:
        """Re-check this client's account; no implicit login or password re-use."""
        if self._closed:
            return LoginResult(LoginStatus.CLOSED)
        if self._account is None or self._session is None:
            return LoginResult(LoginStatus.NOT_AUTHENTICATED)
        try:
            result = self._read_identity(self._request("GET", _BASE_URL), self._account)
            return self._finish(result)
        except _FlowFailure as failure:
            return self._finish(LoginResult(failure.status, http_status=failure.http_status))
        except BaseException:
            self._clear_session()
            raise

    def close(self):
        """Invalidate local state, without requesting server logout or erasing Python memory."""
        self._closed = True
        self._clear_session()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
