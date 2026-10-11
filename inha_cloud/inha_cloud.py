"""인하대학교 계정 소유 확인을 위한 로그인 클라이언트."""

import os
from enum import Enum
from typing import Dict, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


class LoginStatus(str, Enum):
    SUCCESS = "success"
    REJECTED = "rejected"
    ADDITIONAL_AUTH = "additional_auth"
    PAGE_CHANGED = "page_changed"
    NETWORK_ERROR = "network_error"
    NOT_ATTEMPTED = "not_attempted"


MESSAGES = {
    LoginStatus.SUCCESS: "학교 계정 소유 확인에 성공했습니다.",
    LoginStatus.REJECTED: "로그인이 완료되지 않았습니다. 학교 사이트에서 계정 상태를 확인하세요.",
    LoginStatus.ADDITIONAL_AUTH: "학교 사이트의 추가 인증이 필요합니다. 자동 인증을 완료하지 않았습니다.",
    LoginStatus.PAGE_CHANGED: "예상한 인증 정보를 찾지 못했습니다. 학교 화면 구조 확인이 필요합니다.",
    LoginStatus.NETWORK_ERROR: "학교 사이트 요청에 실패했습니다. 네트워크 상태를 확인하세요.",
    LoginStatus.NOT_ATTEMPTED: "아직 로그인을 시도하지 않았습니다.",
}


class InhaCloud:
    """인증 완료를 확인할 수 있을 때만 성공을 반환한다."""

    base_url = "https://cloud.inha.ac.kr"
    login_url = base_url + "/auth/login"

    def __init__(self, username: Optional[str] = None,
                 password: Optional[str] = None, *, timeout: float = 15,
                 load_env: bool = False):
        if timeout <= 0:
            raise ValueError("요청 제한 시간은 0보다 커야 합니다.")
        if load_env:
            load_dotenv()
        self.username = username or (os.getenv("INHA_USERNAME") if load_env else None)
        self.password = password or (os.getenv("INHA_PASSWORD") if load_env else None)
        self.timeout = timeout
        self._session = requests.Session()
        self.status = LoginStatus.NOT_ATTEMPTED
        self.account_id: Optional[str] = None
        self.student_id: Optional[str] = None
        self.name: Optional[str] = None

    @property
    def message(self) -> str:
        return MESSAGES[self.status]

    def _request(self, method: str, url: str, data=None):
        """인증 정보가 다른 호스트로 전송되지 않도록 이동을 직접 확인한다."""
        for _ in range(6):
            parsed = urlparse(url)
            if (parsed.scheme != "https" or parsed.hostname != "cloud.inha.ac.kr"
                    or parsed.port not in (None, 443) or parsed.username or parsed.password):
                raise ValueError("학교 인증 호스트 밖으로 이동할 수 없습니다.")
            response = self._session.request(
                method, url, data=data, timeout=self.timeout, allow_redirects=False)
            response.raise_for_status()
            if response.status_code not in (301, 302, 303, 307, 308):
                return response
            location = response.headers.get("Location")
            if not location:
                raise ValueError("이동할 주소가 없습니다.")
            url = urljoin(url, location)
            if response.status_code == 303 or (
                    response.status_code in (301, 302) and method == "POST"):
                method, data = "GET", None
        raise ValueError("학교 인증 페이지의 이동 횟수가 너무 많습니다.")

    def _read_identity(self, response) -> Optional[Dict[str, str]]:
        soup = BeautifulSoup(response.text, "html.parser")
        path = urlparse(response.url).path.lower()
        if path.startswith("/auth/mfa") or soup.select_one('input[name="pincode"]'):
            self.status = LoginStatus.ADDITIONAL_AUTH
            return None
        if soup.select_one('form[action="/auth/login"]'):
            self.status = LoginStatus.REJECTED
            return None
        header = soup.select_one(".loginHeader[data-userid]")
        account_id = str(header.get("data-userid", "")).strip() if header else ""
        if not account_id:
            self.status = LoginStatus.PAGE_CHANGED
            return None
        self.account_id = account_id
        # 기존 호출자 호환용이며 학번 또는 재학 여부를 보증하지 않는다.
        self.student_id = account_id
        self.name = header.get_text(" ", strip=True)
        self.status = LoginStatus.SUCCESS
        return {"account_id": account_id, "student_id": account_id, "name": self.name}

    def login(self, username: Optional[str] = None,
              password: Optional[str] = None) -> bool:
        account = username or self.username
        secret = password or self.password
        self.account_id = self.student_id = self.name = None
        self.status = LoginStatus.NOT_ATTEMPTED
        # 이전 사용자의 쿠키로 다른 계정 인증을 성공 처리하지 않는다.
        self._session.cookies.clear()
        payload = {}
        try:
            if not account or not secret:
                raise ValueError("학교 계정 아이디와 비밀번호가 필요합니다.")
            page = self._request("GET", self.base_url)
            soup = BeautifulSoup(page.text, "html.parser")
            form = soup.select_one('form[action="/auth/login"]')
            csrf = form.select_one('input[name="_csrf"]') if form else None
            domain = form.select_one('input[name="loginDomain"]') if form else None
            if (not csrf or not csrf.get("value") or not domain
                    or domain.get("value") != "inha.ac.kr"):
                self.status = LoginStatus.PAGE_CHANGED
                return False
            payload = {field["name"]: field.get("value", "")
                       for field in form.select('input[type="hidden"][name]')}
            payload.update(userid=account, password=secret)
            response = self._request("POST", self.login_url, data=payload)
            if self._read_identity(response):
                return True
            # 로그인 뒤 빈 응답인 경우만 홈에서 인증 정보를 다시 확인한다.
            if self.status == LoginStatus.PAGE_CHANGED:
                return bool(self.fetch_login_info())
            return False
        except requests.RequestException:
            self.status = LoginStatus.NETWORK_ERROR
            return False
        except ValueError:
            self.status = LoginStatus.PAGE_CHANGED
            raise
        finally:
            payload.clear()
            self.password = None
            secret = None
            if self.status != LoginStatus.SUCCESS:
                self._session.cookies.clear()

    def fetch_login_info(self) -> Optional[Dict[str, str]]:
        self.account_id = self.student_id = self.name = None
        try:
            return self._read_identity(self._request("GET", self.base_url))
        except requests.RequestException:
            self.status = LoginStatus.NETWORK_ERROR
            return None
        except ValueError:
            self.status = LoginStatus.PAGE_CHANGED
            return None

    def close(self):
        """로컬 쿠키와 연결을 정리한다. 학교 서버의 로그아웃을 보증하지 않는다."""
        self.password = None
        self.account_id = self.student_id = self.name = None
        self.status = LoginStatus.NOT_ATTEMPTED
        self._session.cookies.clear()
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
