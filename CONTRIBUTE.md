# Contributing Guidelines

## English

1. Fork the repository and create a branch.
2. Set up with uv (Python 3.11+): `uv sync --locked`.
3. Run the tests: `uv run --locked python -m unittest discover -s tests -v`.
4. Use scripted transports or numeric-loopback HTTPS with synthetic fixtures only. Tests activate a loopback-only Python socket guard; CI also loads it at startup through `tests/_network`. Never contact school servers from tests or CI or include real credentials, cookies or response bodies in code, issues or logs. Temporary TLS keys must be generated and removed by the fixture.
5. Keep the public API to `InhaCloud`, `LoginStatus`, `LoginResult`, `Identity`; do not add compatibility shims.
6. Submit a pull request describing the change and the checks you ran.

## 한국어

1. 저장소를 포크하고 브랜치를 만듭니다.
2. uv(Python 3.11 이상)로 설정합니다: `uv sync --locked`.
3. 테스트를 실행합니다: `uv run --locked python -m unittest discover -s tests -v`.
4. 테스트는 합성 자료와 로컬 모의 전송 또는 숫자 루프백 HTTPS만 사용합니다. 테스트는 Python 소켓의 루프백 제한 가드를 켜고, CI는 `tests/_network`로 시작 시에도 불러옵니다. 학교 서버에 요청하거나 실제 인증 정보·쿠키·응답 원문을 코드·이슈·로그에 넣지 않습니다. TLS 키는 임시로 생성하고 정리합니다.
5. 공개 API는 `InhaCloud`, `LoginStatus`, `LoginResult`, `Identity`로 유지하고 호환 계층을 추가하지 않습니다.
6. 변경 내용과 실행한 검사를 pull request에 적습니다.

## 릴리스·PyPI 배포

- `main`의 해당 커밋에 대한 CI 전체가 성공한 뒤 버전과 일치하는 `vX.Y.Z` 태그·GitHub Release를 만듭니다. 실제 학교 인증 검증 여부를 릴리스 설명에 명시합니다.
- GitHub Release에는 성공한 CI의 `dist` 아티팩트와 SHA-256 매니페스트를 첨부합니다. 로컬에서 다른 파일을 다시 빌드해 대체하지 않습니다.
- `.github/workflows/publish.yml`은 게시된 릴리스 태그의 커밋과 일치하는 성공한 `main` CI를 확인하고, 그 실행의 `dist` 아티팩트만 PyPI에 게시합니다.
- 인증은 GitHub OIDC Trusted Publishing만 사용합니다. PyPI 프로젝트 관리자가 GitHub 소유자 `inha-oss`, 저장소 `inha-login-fetcher`, 워크플로 `publish.yml`, 환경 `pypi`를 등록해야 합니다. 등록되지 않으면 게시가 실패하며 API 토큰으로 우회하지 않습니다.
- 릴리스 게시 시 자동 실행합니다. 외부 인증 설정 후 같은 릴리스를 다시 게시하려면 `gh workflow run publish.yml --repo inha-oss/inha-login-fetcher --ref main -f tag=v0.4.0`을 사용합니다.
- API 토큰·비밀번호를 저장소나 워크플로 인자로 넣지 않습니다. GitHub 릴리스 성공과 PyPI 게시 성공은 별도로 확인합니다.

