# Changelog

## 0.4.0

Breaking, pre-1.0. No compatibility layer.

- Installable package (`pyproject.toml`); console script `inha-login-fetcher` and `python -m inha_cloud`. Root `main.py`, `setup.py`, `requirements.txt` removed.
- Public API: `from inha_cloud import InhaCloud, LoginStatus, LoginResult, Identity`. `login()` and `fetch_login_info()` return an immutable `LoginResult`; use `.success`.
- Removed: `student_id`, mutable `client.status`/`account_id`/`name`, constructor credentials, mutable host targets, dotenv/env loading in the library, and the `python-dotenv` dependency. Password CLI options remain unsupported.
- Env credentials are read only with CLI `--env`; no `.env` file reading.
- Windows checks the actual console input handle rather than accepting `NUL` as an interactive terminal.
- Fixed host `https://cloud.inha.ac.kr`; fresh session per login with `trust_env` disabled; no retries; 307/308 after POST blocked.
- Login succeeds only if the account ID exactly matches the requested username; otherwise `identity_mismatch`.
- MFA is detected (`additional_auth`), never submitted.
- New statuses: `unsafe_destination`, `identity_mismatch`, `rate_limited`, `service_unavailable`, `http_error`, `not_authenticated`, `closed`, `invalid_input`.
- Malformed redirect destinations become structured failures and close the session. Empty MFA pages cannot fall through to a successful homepage check.
- Redirect bodies are not eagerly buffered by requests; response parsing is size- and content-type-bounded.
- MFA checks use Requests URL canonicalization before following encoded or dot-segment redirects.
- Cancellation and unexpected exceptions invalidate authentication and close the session before propagating; unrepresentably large timeouts raise `ValueError`.
- Nonstandard wire status codes outside 100–599 produce `http_error` without retaining authentication or exposing an internal exception.
- Real loopback HTTPS regressions cover certificates, cookies, read timeouts, malformed framing, gzip and decoded-size limits; Python socket guards prevent external test traffic.
- Raised the Requests floor to 2.33.0 after advisory review. Test-only certificate generation uses cryptography 50.x; locked and lowest-direct dependency combinations were audited.
- Canonical package version, uv dependency lock and immutable Node 24 Action revisions; offline Python 3.11–3.14 test/build/install workflow.
- PyPI Trusted Publishing workflow reuses the successful main CI artifact for the exact published release commit; no local rebuild or long-lived upload token.
- Real login and post-login identity mapping remain unverified.
