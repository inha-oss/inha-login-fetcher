# 인증 모듈 검증 기록 (0.4.0)

## 검증 명령

학교 서버에 추가 요청을 보내지 않고 합성 응답과 숫자 루프백 HTTPS로 검증했다. 의존 패키지 다운로드·취약점 정보 조회에는 PyPI 계열 서비스를 사용했다.

```sh
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
uv build
uvx twine check --strict dist/*
```

설치된 CLI 확인(깨끗한 환경에서 wheel 설치 후):

```sh
inha-login-fetcher --help
inha-login-fetcher --version
python -m inha_cloud --help
```

### 실행 결과 (2026-10-24, macOS arm64)

- Python 3.11.17·3.12.15·3.13.16·3.14.8에서 58개 회귀 항목을 검증했다. 최초 실행은 57개가 통과했고, 새 HTTPS 리다이렉트 테스트가 선택적인 HTTP 코드까지 필수로 단정한 검사는 제거한 뒤 해당 테스트를 4개 버전에서 재실행해 통과했다. 최종 58개 일괄 실행은 Python 3.11의 최소 의존성 조합·설치된 sdist 양쪽에서 통과했다.
- 기존 구현에서 다른 계정 ID가 성공 처리되는 문제를 로컬로 재현한 후, 새 구현은 `identity_mismatch`로 거절함을 확인했다.
- 잘못된 리다이렉트 URL의 구조화 실패·세션 정리, MFA 경로를 경유한 성공 오판 방지, POST 재전송 금지, 대형 리다이렉트 본문 미버퍼링을 회귀 검증했다. `/auth/%6dfa/pin`과 점 경로도 Requests의 URL 정규화 후 MFA로 감지하여 이동 전에 중단한다.
- `uv build`로 wheel과 sdist 생성, `uvx twine check --strict dist/*` 통과. `uv pip check`로 설치 의존성 호환을 확인했다.
- 저장소 밖의 새 Python 3.11 환경에 sdist를 설치하고 해당 site-packages에서 패키지를 불러오는 것을 확인했다. sdist에 포함된 테스트와 루프백 가드로 전체 58개가 통과했으며, 콘솔·모듈 진입점의 help/version도 실행했다.
- 설치된 모듈 CLI를 실제 루프백 HTTPS 서버와 연결해 성공·인증 거절·인코딩된 MFA·비표준 상태 코드·계정 불일치·미신뢰 인증서·실제 읽기 타임아웃 7개 시나리오를 실행했다. 상태·종료 코드·후속 요청 차단을 확인했고 출력에 신원·비밀번호가 없었다.
- 설치된 CLI를 PTY에서 실행해 아이디/비밀번호 입력을 진행했다. 합성 인증은 성공했고, 비밀번호는 터미널 출력에 표시되지 않았다.
- `actionlint` 통과. CI는 Python 3.11–3.14 및 Linux/macOS/Windows에서 실행하며 배포 전에 전체 성공이 필요하다. 최초 원격 실행에서 발견한 Windows 오류와 배포 게이트는 아래에 기록했다.
- 버전은 `_version.py` 한 곳에서 관리하고, `uv.lock`의 런타임 의존성 조합을 개발·CI 테스트에서 사용한다. 일반 wheel 설치에는 pyproject의 호환 버전 범위가 적용되며 빌드 도구·twine까지 이 lock으로 고정한 것은 아니다. Actions 리비전은 GitHub API로 확인한 커밋 SHA로 고정했다.

합성 응답 성공은 실제 학교 로그인을 증명하지 않는다. 빌드 산출물은 `dist/inha_cloud-0.4.0-py3-none-any.whl`, `dist/inha_cloud-0.4.0.tar.gz`이다. 게시 여부는 [GitHub Releases](https://github.com/inha-oss/inha-login-fetcher/releases)와 [PyPI](https://pypi.org/project/inha-cloud/)에서 별도로 확인한다.

## 추가 사전 검증

### 전송·실패 경계

- `tests/test_https.py`: 8개 테스트 메서드, 43개 합성 HTTPS 시나리오. 실제 Requests/urllib3/SSL을 사용하며 TCP 목적지만 `127.0.0.1`로 바꾸고 논리 URL·SNI·인증서 호스트·Host 헤더·쿠키 출처는 유지한다.
- 임시 CA/인증서/키로 정상 TLS, 다른 호스트 인증서, 미신뢰 CA, 만료 인증서를 확인했다. 인증서 검증 실패 시 HTTP 요청과 비밀번호 전송은 없었다.
- 사전 쿠키를 요구하는 로그인 POST→303→계정 확인, 다른 도메인의 쿠키 거절, 세션 만료 후 인증 무효화를 검증했다.
- 최초 GET·인증 POST·계정 확인 단계에서 헤더/본문 읽기 타임아웃, 잘못된 상태 줄/청크/압축·연결 종료를 확인했다. 재시도나 비밀번호 재전송은 없었다. 잘린 본문 검증은 Content-Length의 버전별 동작 대신 청크 전송을 사용했다.
- 일반/압축 응답 모두 **압축 해제 후** 1 MiB 정확 경계는 허용하고 1바이트 초과는 인증 정보 전송 전에 차단했다.
- 600·999 응답은 `http_error`, `http_status=None`으로 처리하고 기존 인증도 무효화한다. 합성 어댑터와 실제 HTTPS 양쪽으로 확인했다.
- `KeyboardInterrupt`와 예상하지 못한 예외가 발생하면 세션·쿠키·이전 계정을 정리하고 예외를 다시 발생시킨다. 과도하게 큰 정수 timeout은 `OverflowError` 대신 `ValueError`로 거절한다.
- 임시 netrc·프록시·존재하지 않는 환경 지정 CA를 설정해도 사용하지 않으며, ambient Authorization 헤더가 추가되지 않음을 확인했다.
- `tests/_network/sitecustomize.py`는 외부 DNS·connect·connect_ex·sendto를 차단한다. 차단 동작도 별도 스모크로 실행했다. Python 회귀 방지 장치이지 OS 샌드박스나 모든 네이티브 통신 차단의 보증은 아니다. 테스트 인증서·키·서버는 임시 생성 후 제거한다.

### 의존성·정적 검사

`uv export --locked --no-emit-project --no-hashes --format requirements-txt`와 `uv pip compile pyproject.toml --group dev --resolution lowest-direct --python-version 3.11`로 별도 입력을 만들었다. 각각 `uvx pip-audit --no-deps --disable-pip --vulnerability-service pypi --format json --requirement <임시파일>`로 조회했다(pip-audit 2.10.1).

| 조합 | 검사한 패키지 | 알려진 취약점 |
| --- | ---: | ---: |
| 최종 lock, 런타임·개발 의존성 | 11 | 0 |
| 해당 시점 lowest-direct, 런타임·개발 의존성 | 11 | 0 |

- 런타임은 8개, TLS 인증서 생성용 개발 의존성은 cryptography·cffi·pycparser이다. cryptography는 일반 wheel 설치의 런타임 의존성이 아니다.
- 이전 Requests 하한 2.32.4에서 `CVE-2026-25645`를 확인해 `>=2.33.0,<3`으로 올렸다. 해당 extract_zipped_paths 경로의 이 클라이언트 내 악용 가능성을 증명한 것은 아니다.
- 개발용 cryptography의 이전 허용 범위와 49.0.0 잠금에서 알려진 취약점을 확인하여 `>=50,<51`, 잠금 50.0.2로 변경했다. 하한 조합은 50.0.0이다. 취약점 제외 옵션은 사용하지 않았다.
- 최저 직접 의존성 조합(Requests 2.33.0, BeautifulSoup 4.13.1, cryptography 50.0.0)을 새 Python 3.11 환경에 설치하여 전체 테스트가 통과했다. 모든 허용 버전 조합을 열거한 검증은 아니다.
- `uvx bandit -r inha_cloud -f json`: 오류·탐지 항목 0. `actionlint`도 통과했다.
- 취약점 조회는 당시 데이터베이스에 알려진 항목만 대상으로 하며 미발견 취약점 부재를 증명하지 않는다. 빌드/검사 도구 전체를 위 의존성 감사 범위에 포함한 것은 아니다.

## 배포 전 원격 검증

- 최초 원격 [CI 40062147104](https://github.com/inha-oss/inha-login-fetcher/actions/runs/40062147104)는 Linux/macOS 테스트·배포본 검사·설치된 CLI 검사를 통과했지만, Windows Python 3.11–3.14의 입력 누락 검사가 실패했다. `NUL` 표준입력을 TTY로 오인하여 `getpass`가 30초 이상 대기한 문제였다.
- Windows 입력은 `GetConsoleMode`로 실제 콘솔 핸들을 확인하도록 수정했다. 실제 하위 프로세스의 `DEVNULL` 입력 거절 검사를 유지하며, 프롬프트 단위 검증만 OS 터미널 감지와 분리했다. 수정 후 로컬 CLI 20개 검사가 통과했다. Windows 확인은 원격 CI에서 수행한다.
- 구형 Action의 Node 20 종료 경고를 확인하여 공식 Node 24 리비전으로 갱신했다: checkout v7.0.1, setup-uv v10.3.2, upload-artifact v7.0.2, download-artifact v8.0.2. 커밋 SHA와 각 `action.yml`의 `runs.using`을 확인했다.
- 현재 GitHub 인증은 PR 생성이 GraphQL/REST 모두 거절되어 브랜치 push로 검증한다. 브랜치 CI 성공 전 main에 통합하지 않고, PyPI 게이트는 태그 커밋과 정확히 같은 main push의 CI 전체 성공을 다시 요구한다.
- 릴리스 검증은 테스트 12개 조합·wheel/sdist 빌드 1개·설치된 CLI 6개 조합을 모두 포함한다. [현재 CI 결과](https://github.com/inha-oss/inha-login-fetcher/actions/workflows/ci.yml)가 배포 게이트의 기준이다.
- `uv publish --dry-run --trusted-publishing never`로 파일 검사를 실행했다. 실제 업로드는 하지 않았으며, PyPI 게시에는 프로젝트 소유자가 등록한 Trusted Publisher가 필요하다.

## 익명 관찰 (2026-10-24, 로그인 요청 없음)

- `cloud.inha.ac.kr` 루트: 302로 `/t/inha.ac.kr`.
- `/t/inha.ac.kr`: 200, `POST /auth/login` 양식과 `_csrf`, `loginDomain`, `userid`, `password`, `SAMLRequest`, `RelayState`, `requestId`, `referer` 필드.
- `GET /auth/login`: 404. POST 양식이 존재하므로 POST 미지원의 증거가 아님.
- 공개 `validator.js`가 `POST /auth/mfa/pin`, `/otp`를 참조.
- `api.inha.ac.kr`: 루트 200(ASP.NET 안내), 위 cloud 전용 경로 4개는 404. 대체 호스트 근거 없음.

## 미확인 사항

- 실제 계정 로그인 성공. 비밀번호·OTP를 사용하지 않았고 POST/로그인/OTP 요청을 보내지 않았다.
- 로그인 후 `.loginHeader[data-userid]`가 로그인 아이디와 같은 값을 갖는지(정확 일치 규칙은 보수적 가정이며 실제 검증 전).
- 재학 여부. `display_name`이 실명인지.
- 추가 인증이 요구되는 계정의 실제 흐름. 감지만 하며 자동 제출하지 않는다.
- 학교 서버 측 로그아웃(`close()`는 로컬 정리만 한다).
- 모의 응답 테스트는 판별·실패 처리 규칙만 확인하며 실제 학교 응답과의 일치를 증명하지 않는다. 이전 버전의 모의 테스트 13개 통과도 실제 로그인을 증명하지 않았다.

## 다음 단계

사용자가 로컬 CLI(`inha-login-fetcher`)로 실제 계정을 시험하고 **상태 코드만** 공유한다. `page_changed`나 `identity_mismatch`라면 추가 인증 여부와 로그인 후 화면의 비민감 구조를 확인한 뒤 규칙을 수정한다. 비밀번호·쿠키·토큰·응답 원문은 공유하지 않는다. 실제 계정 인증이 검증된 뒤 GitHub 조직 가입 연동을 진행한다.
