# 인하대학교 계정 소유 확인

`cloud.inha.ac.kr`의 학교 계정 로그인을 확인하는 Python 패키지(0.4.0)입니다. `inha-oss` 조직 가입에 필요한 **학교 계정 소유 확인**을 준비하며, 학생 신분이나 현재 재학 여부를 판정하지 않습니다.

실제 계정 로그인과 로그인 후 계정 ID 매핑은 **아직 검증하지 않았습니다.** 운영 가능하거나 완전히 안전한 인증 서비스라고 보증하지 않습니다. 공식 SSO 연동이 아니라 학교 비밀번호로 웹 로그인하는 클라이언트이며, 학교의 공식 연동 승인은 확인되지 않았습니다. GitHub 자동 가입 기능은 포함하지 않습니다.

0.4.0은 0.3 이하와 호환되지 않는 변경입니다(1.0 이전). 호환 계층은 제공하지 않습니다.

## 설치

Python 3.11 이상이 필요합니다. [GitHub Releases](https://github.com/inha-oss/inha-login-fetcher/releases)의 wheel 또는 저장소 소스에서 설치합니다. PyPI 게시 여부와 버전은 [프로젝트 페이지](https://pypi.org/project/inha-cloud/)에서 확인하세요.

```sh
git clone https://github.com/inha-oss/inha-login-fetcher.git
cd inha-login-fetcher
uv sync --locked
source .venv/bin/activate
```

Windows PowerShell에서는 활성화 명령을 `.venv\Scripts\Activate.ps1`로 바꿉니다. 활성화하지 않으면 `uv run --locked inha-login-fetcher ...` 또는 `uv run --locked python -m inha_cloud ...`를 사용합니다.

## CLI

```sh
inha-login-fetcher --help
inha-login-fetcher --version
inha-login-fetcher                      # 아이디 입력 후 비밀번호는 getpass로 입력
inha-login-fetcher --username <아이디>
inha-login-fetcher --json               # 신원 정보 없이 상태·안내·HTTP 코드를 JSON으로 출력
python -m inha_cloud                    # 동일한 CLI
```

- 비밀번호 명령행 옵션은 없습니다. 대화형 입력은 `getpass`를 사용하며, 화면 표시 입력으로 대체(`GetPassWarning`)되면 거부합니다.
- 환경 변수는 `--env`를 명시할 때만 읽습니다(`INHA_USERNAME`, `INHA_PASSWORD`, 프로세스 환경 변수만). `.env` 파일은 읽지 않습니다.
- 터미널이 아니고 `--env`로 완전한 인증 정보가 없으면 네트워크 요청 전에 `invalid_input`으로 실패합니다. Windows는 실제 콘솔 핸들도 확인해 `NUL`·파이프에서 비밀번호 입력을 기다리지 않습니다.
- `--timeout <초>`는 소켓 읽기 시간 제한입니다(유한한 양수). 연결 제한은 5초 또는 지정값 중 작은 값이며 전체 인증 과정의 총 소요 시간 제한은 아닙니다.
- 이름·계정 ID·비밀번호·쿠키·예외·응답 원문을 출력하지 않습니다. `--json`은 `status`, `message`, `http_status`만 출력합니다.
- 종료 코드: 0 `success`; 1 `rejected`, `not_authenticated`; 2 `invalid_input`, `page_changed`, `unsafe_destination`, `identity_mismatch`, `http_error`, `closed`; 3 `additional_auth`; 4 `network_error`, `rate_limited`, `service_unavailable`; 70 예상하지 못한 내부 오류(안전한 일반 문구만 출력); 130 중단(KeyboardInterrupt).

실제 계정 시험 결과는 상태 코드만 공유하고, 인증 정보는 채팅·저장소·검증 기록에 넣지 않습니다.

## 라이브러리 사용

```python
from getpass import GetPassWarning, getpass
import warnings
from inha_cloud import InhaCloud

account = input("학교 계정 아이디: ").strip()
with warnings.catch_warnings():
    warnings.simplefilter("error", GetPassWarning)
    password = getpass("학교 계정 비밀번호: ")
try:
    with InhaCloud(timeout=15) as client:
        result = client.login(account, password)
finally:
    password = None

if result.success:
    print(result.identity.account_id)
else:
    print(result.status.value, result.message)
```

API:

- `InhaCloud(*, timeout=15)`: 인증 정보·`base_url`·dotenv 인자가 없습니다. `timeout`은 float로 표현 가능한 유한한 양수여야 하며(`bool` 불가) 아니면 `ValueError`입니다. 호스트는 `https://cloud.inha.ac.kr`로 고정되고 대체 호스트로 우회하지 않습니다.
- `client.login(username, password) -> LoginResult`, `client.fetch_login_info() -> LoginResult`, `client.close()`, 컨텍스트 관리자.
- `LoginResult(status, identity=None, http_status=None)`: 불변. `.success`(bool), `.message`(고정 한국어 문구)를 제공합니다. **`.success`로 판별하세요.** `bool(result)`는 `TypeError`를 발생시킵니다. `repr`에는 상태·HTTP 코드만 있고 계정 정보는 없습니다. `identity`는 성공일 때만 있습니다. `http_status`는 100–599 또는 `None`이며, 범위 밖의 비표준 응답은 `http_error`와 `None`으로 처리합니다.
- `Identity(account_id, display_name)`: 불변, `repr`에 값을 노출하지 않습니다. `student_id` 별칭은 없으며 재학이나 학번을 의미하지 않습니다. `display_name`은 화면 헤더의 표시 문구이고 확인된 실명이 아닙니다.
- `client.status`, `client.account_id` 같은 변경 가능한 공개 속성은 없습니다.

`LoginStatus` 값: `success`, `rejected`, `additional_auth`, `page_changed`, `network_error`, `invalid_input`, `unsafe_destination`, `identity_mismatch`, `rate_limited`, `service_unavailable`, `http_error`, `not_authenticated`, `closed`.

| 상태 | 의미 |
| --- | --- |
| `success` | 로그인 후 화면에서 요청한 아이디와 정확히 일치하는 계정 ID를 확인함 |
| `rejected` | 인증 미완료(로그인 화면 재표시, HTTP 401/403). 비밀번호 오류를 확정하지 않음 |
| `additional_auth` | `/auth/mfa` 경로 또는 PIN/OTP 입력 화면을 감지함 |
| `page_changed` | 기대한 로그인 양식이나 계정 정보를 찾지 못함 |
| `network_error` | 시간 초과 등 요청 오류. 로그인 결과가 불명일 수 있음 |
| `invalid_input` | 빈 값·잘못된 입력. 네트워크 요청 없음 |
| `unsafe_destination` | 학교 호스트 밖·비HTTPS 인증 정보 전송 대상, 또는 POST 후 307/308 이동 |
| `identity_mismatch` | 화면의 계정 ID가 요청한 아이디와 다름. 성공으로 처리하지 않음 |
| `rate_limited` | HTTP 429 |
| `service_unavailable` | HTTP 5xx |
| `http_error` | 위 분류에 해당하지 않는 예상 밖 HTTP 응답 |
| `not_authenticated` | 로그인 성공 전에 `fetch_login_info()` 호출. 네트워크 요청 없음 |
| `closed` | 닫힌 클라이언트 사용 |

## 동작과 한계

- 로그인 양식은 고정 호스트의 `POST /auth/login`이며 비어 있지 않은 `_csrf`, `loginDomain=inha.ac.kr`, `userid`, `password` 입력이 있어야 합니다. 화면 구조가 다르면 `page_changed`, 인증 목적지가 다르면 `unsafe_destination`입니다. 응답 본문은 최대 1 MiB이며 비어 있지 않은 비HTML 응답이나 비동기 처리(202)를 성공으로 보지 않습니다.
- 성공 판별: 비밀번호·로그인·추가 인증 양식이 없고, 비어 있지 않은 `.loginHeader[data-userid]`가 하나이며 그 값이 바깥 공백을 제거한 요청 아이디와 정확히 같을 때. 이 매핑은 실제 로그인으로 검증하지 않았습니다.
- 추가 인증(MFA)은 감지만 하며 PIN/OTP를 자동 제출하지 않습니다.
- 로그인마다 새 `requests.Session`을 만들고 `trust_env`를 끄므로 환경의 프록시·netrc·환경 지정 CA 설정을 사용하지 않고 기본 TLS 검증으로 직접 연결합니다. 자동 재시도는 없으며 비밀번호 POST는 호출당 최대 1회입니다. POST 뒤 301/302/303 이동은 데이터 없이 GET으로 따라가고, POST를 보존하는 307/308은 차단합니다. GET의 동일 호스트 리다이렉트는 허용하되 전체 이동은 최대 5회입니다.
- 최종 로그인 응답이 빈 200 본문 또는 204일 때만 `GET /`을 한 번 시도합니다. 202 응답이나 비어 있지 않은 알 수 없는 화면에는 쓰지 않습니다. MFA 경로는 Requests가 실제 전송할 URL로 정규화한 뒤 검사하므로 인코딩·점 경로가 있어도 따라가기 전에 중단합니다.
- 모든 실패는 세션을 정리합니다. 새 로그인은 이전 세션·계정 정보를 무효화하고, `fetch_login_info()` 실패는 이전 인증을 무효화합니다. `KeyboardInterrupt`와 예상하지 못한 내부 예외도 세션을 정리한 뒤 그대로 다시 발생시킵니다.
- `LoginResult`는 당시 관찰의 스냅숏이며 현재 인증이나 계정 소유의 지속적 증명이 아닙니다.
- `close()`는 로컬 세션을 닫을 뿐 학교 서버에서 로그아웃하지 않으며, 닫힌 클라이언트는 재사용할 수 없습니다.
- 클라이언트는 동시 공유용이 아닙니다. 사용자 작업마다 컨텍스트 하나를 쓰세요.
- 비밀번호를 클라이언트·결과에 저장하거나 기록하지 않지만 Python 메모리에서의 완전 삭제는 보증하지 못합니다. 실패 응답에는 예외 원문이나 인증 정보가 없습니다.

## 관찰 근거

2026-10-24 익명 확인: `cloud.inha.ac.kr` 루트는 302로 `/t/inha.ac.kr`로 이동하고, 이 화면(200)에 `POST /auth/login` 양식(`_csrf`, `loginDomain`, `userid`, `password`, `SAMLRequest`, `RelayState`, `requestId`, `referer`)이 있었습니다. `GET /auth/login`은 404였으며 POST 양식이 있으므로 이 404가 POST 미지원을 뜻하지는 않습니다. 공개 `validator.js`는 `POST /auth/mfa/pin`, `/otp`를 참조합니다. `api.inha.ac.kr`는 같은 경로에서 404였고 대체 호스트로 삼을 근거가 없어 사용하지 않습니다. 로그인 요청은 보내지 않았습니다.

미확인: 실제 로그인 성공, 로그인 후 `.loginHeader[data-userid]`와 계정 ID의 대응, 재학 여부, 서버 측 로그아웃. 합성 학교 화면과 로컬 HTTPS 검증은 클라이언트의 판별 규칙·전송 동작만 확인합니다. 포털 가입 서버에 연결하기 전에 실제 계정 검증과 추가 인증 대응을 확인해야 합니다.

검증 절차는 [docs/verification.md](docs/verification.md), 변경 내역은 [CHANGELOG.md](CHANGELOG.md), 기여 방법은 [CONTRIBUTE.md](CONTRIBUTE.md)를 참고하세요.

## 라이선스

[MIT](LICENSE)
