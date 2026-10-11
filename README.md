# 인하대학교 계정 소유 확인

`cloud.inha.ac.kr`의 학교 계정 로그인을 확인하는 Python 모듈입니다. `inha-oss` 조직 가입에 필요한 **학교 계정 소유 확인**을 준비하며, 학생 신분이나 현재 재학 여부를 판정하지 않습니다.

현재 버전은 로그인 처리와 실패 구분을 보완한 검증 준비 단계입니다. 실제 계정 로그인은 아직 검증하지 않았으며, 운영 가능한 인증 서비스라고 보증하지 않습니다. GitHub 자동 가입 기능은 다음 단계입니다.

## 설치와 검증

```sh
git clone https://github.com/inha-oss/inha-login-fetcher.git
cd inha-login-fetcher
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python main.py
```

마지막 명령은 아이디를 묻고 비밀번호를 화면에 표시하지 않고 입력받습니다. 비밀번호를 명령행 인자로 전달하는 `-p` 옵션은 제거했습니다. 기본 실행은 환경 변수나 `.env`를 읽지 않습니다. 기존 환경 변수 설정을 사용하려면 `python main.py --env`로 명시합니다. 인증 정보는 로컬에서만 입력하고 채팅·저장소·검증 기록에 넣지 않습니다.

CLI는 이름·계정 ID·비밀번호·쿠키·응답 원문을 출력하지 않고 결과 코드만 출력합니다. 실제 로그인 검증 결과는 결과 코드만 공유하면 됩니다.

| 코드 | 의미 |
| --- | --- |
| `success` | 로그인된 화면의 계정 ID를 확인함 |
| `rejected` | 다시 로그인 화면이 표시되어 인증 미완료 |
| `additional_auth` | 추가 인증 경로나 PIN 화면을 감지함 |
| `page_changed` | 기대한 로그인 양식이나 계정 정보를 찾지 못함 |
| `network_error` | 시간 초과 등 요청 오류 |

`rejected`는 비밀번호 오류를 확정하는 코드가 아닙니다. 계정 상태·학교 응답에 따라 로그인이 완료되지 않을 수 있습니다. 추가 인증 감지는 확인 가능한 경로·필드에 한정되며 새로운 학교 인증 방식은 화면 변경으로 분류될 수 있습니다.

## 라이브러리 사용

```python
from getpass import getpass
from inha_cloud.inha_cloud import InhaCloud

with InhaCloud() as client:
    account = input("학교 계정 아이디: ").strip()
    password = getpass("학교 계정 비밀번호: ")
    try:
        success = client.login(account, password)
    finally:
        password = None
    print(client.message)
    # 성공하면 client.account_id에 확인한 계정 ID가 있다.
```

기존 `login()`의 불리언 반환과 `fetch_login_info()`를 유지합니다. 반환 값에 `account_id`를 추가했습니다. `student_id`는 호환용 별칭이며 학번으로 보증하지 않습니다. 이름은 화면의 전체 표시 문구이고 가입 자격 판정에 사용하지 않습니다. 생성자에 전달한 비밀번호는 로그인 시도 후 제거하므로 재시도 때 다시 전달해야 합니다.

## 보완 내용과 한계

- 현재 로그인 양식에서 CSRF와 숨김 필드를 읽습니다.
- 모든 요청에 시간 제한을 적용하고 학교 인증 호스트 밖으로 이동하는 요청을 차단합니다.
- 새 로그인 전에 쿠키와 기존 인증 정보를 비웁니다.
- 로그인 화면 또는 추가 인증 화면을 성공으로 처리하지 않습니다.
- 실패 시 예외 원문을 출력하지 않습니다. `close()`는 로컬 쿠키와 연결을 정리합니다.
- 비밀번호를 별도 파일에 저장하지 않습니다. Python 메모리의 비밀번호 완전 삭제나 학교 서버 세션 종료를 보증하는 기능은 아닙니다.

2026-10-11 익명 확인에서 `/t/inha.ac.kr`의 로그인 양식과 `/auth/login` 경로가 존재했습니다. 실제 로그인 후 `.loginHeader[data-userid]`가 현재도 유효한지는 미확인입니다. 모의 응답 테스트는 해당 성공 판별 규칙의 동작을 검증하며, 실제 학교 로그인 성공을 증명하지 않습니다.

공식 SSO 연동이 아니라 학교 비밀번호로 웹 로그인하는 클라이언트입니다. 포털 가입 서버에 연결하기 전에 실제 계정 검증과 추가 인증 대응 방식을 확인해야 합니다. GitHub 조직 권한이나 학교 계정 인증 결과를 브라우저가 임의로 제출하는 방식으로 가입을 허용하지 않습니다.

## 라이선스

[MIT](LICENSE)
