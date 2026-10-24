"""Behavioral authentication regressions using requests against an in-memory adapter.

All identities, HTML, keys and passwords here are synthetic. No network is contacted.
"""

from dataclasses import FrozenInstanceError, dataclass, field
import io
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

import requests
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict

from _network import sitecustomize as _network_guard

from inha_cloud import Identity, InhaCloud, LoginResult, LoginStatus
from inha_cloud.inha_cloud import _Session

BASE = "https://cloud.inha.ac.kr"
ACCOUNT = "synthetic-account"
PASSWORD = "synthetic-secret"
FORM = '''<form action="/auth/login" method="POST">
<input type="hidden" name="_csrf" value="synthetic-token">
<input type="hidden" name="loginDomain" value="inha.ac.kr">
<input type="hidden" name="RelayState" value="synthetic-context">
<input type="text" name="userid"><input type="password" name="password">
</form>'''
IDENTITY = f'<div class="loginHeader" data-userid="{ACCOUNT}">합성 표시 문구</div>'


@dataclass
class Page:
    text: str | bytes = ""
    status: int = 200
    headers: dict = field(default_factory=dict)
    url: str | None = None


class CountingBody(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.bytes_read = 0

    def read(self, size=-1):
        data = super().read(size)
        self.bytes_read += len(data)
        return data


class ScriptedAdapter(BaseAdapter):
    def __init__(self, pages):
        self.pages = list(pages)
        self.requests = []
        self.transport = []
        self.bodies = []

    def send(self, request, **kwargs):
        self.requests.append(request)
        self.transport.append(kwargs)
        if not self.pages:
            raise AssertionError("Unexpected request; test has no network fallback")
        page = self.pages.pop(0)
        if isinstance(page, BaseException):
            raise page
        response = requests.Response()
        response.status_code = page.status
        response.url = page.url or request.url
        response.request = request
        response.headers = CaseInsensitiveDict({"Content-Type": "text/html; charset=utf-8", **page.headers})
        response.encoding = requests.utils.get_encoding_from_headers(response.headers)
        response.raw = CountingBody(page.text.encode("utf-8") if isinstance(page.text, str) else page.text)
        self.bodies.append(response.raw)
        return response

    def close(self):
        pass


class ScriptedSession(_Session):
    def __init__(self, pages):
        super().__init__()
        self.adapter = ScriptedAdapter(pages)
        self.mount("https://", self.adapter)
        self.mount("http://", self.adapter)
        self.closed = False

    def close(self):
        self.closed = True
        super().close()


class ClientTests(unittest.TestCase):
    def scripted(self, *scripts):
        sessions = [ScriptedSession(pages) for pages in scripts]
        factory = patch("inha_cloud.inha_cloud._Session", side_effect=sessions)
        self.addCleanup(factory.stop)
        factory.start()
        return sessions

    def test_success_is_exact_account_bound_and_result_is_explicit(self):
        session, = self.scripted([Page(FORM), Page(IDENTITY)])
        with InhaCloud() as client:
            result = client.login(ACCOUNT, PASSWORD)
            self.assertTrue(result.success)
            self.assertEqual(result.identity.account_id, ACCOUNT)
            self.assertEqual(result.identity.display_name, "합성 표시 문구")
            self.assertEqual(result.http_status, 200)
            with self.assertRaises(TypeError):
                bool(result)
            self.assertNotIn(ACCOUNT, repr(result))
            self.assertNotIn(ACCOUNT, repr(result.identity))
            self.assertNotIn(PASSWORD, repr(client.__dict__))
            with self.assertRaises(FrozenInstanceError):
                result.status = LoginStatus.REJECTED
        self.assertTrue(session.closed)

    def test_different_identity_is_rejected_and_not_available_for_later_fetch(self):
        session, = self.scripted([Page(FORM), Page(IDENTITY.replace(ACCOUNT, "different-account"))])
        with InhaCloud() as client:
            result = client.login(ACCOUNT, PASSWORD)
            self.assertEqual(result.status, LoginStatus.IDENTITY_MISMATCH)
            self.assertIsNone(result.identity)
            count = len(session.adapter.requests)
            self.assertEqual(client.fetch_login_info().status, LoginStatus.NOT_AUTHENTICATED)
            self.assertEqual(len(session.adapter.requests), count)
        self.assertTrue(session.closed)

    def test_duplicate_or_blank_identity_never_authenticates(self):
        for html in (IDENTITY + IDENTITY, IDENTITY.replace(ACCOUNT, ""), "<html>Unexpected screen</html>"):
            with self.subTest(html=html):
                session, = self.scripted([Page(FORM), Page(html)])
                with InhaCloud() as client:
                    self.assertEqual(client.login(ACCOUNT, PASSWORD).status, LoginStatus.PAGE_CHANGED)
                self.assertEqual(len(session.adapter.requests), 2)

    def test_login_or_password_form_wins_over_identity_marker(self):
        for html in (FORM + IDENTITY, '<input type="password">' + IDENTITY):
            with self.subTest(html=html):
                self.scripted([Page(FORM), Page(html)])
                with InhaCloud() as client:
                    result = client.login(ACCOUNT, PASSWORD)
                    self.assertEqual(result.status, LoginStatus.REJECTED)
                    self.assertIsNone(result.identity)

    def test_mfa_is_never_success_or_automatically_submitted(self):
        cases = [
            [Page(FORM), Page(status=302, headers={"Location": "/auth/mfa/login"})],
            [Page(FORM), Page(status=302, headers={"Location": "/auth/mfa/pin"})],
            [Page(FORM), Page(status=303, headers={"Location": "/auth/mfa/otp"})],
            [Page(FORM), Page('<input name="pincode">' + IDENTITY)],
            [Page(FORM), Page('<input id="otpCode">' + IDENTITY)],
            [Page(FORM), Page('<form action="/auth/mfa/otp"></form>' + IDENTITY)],
            [Page('<form action="/auth/mfa/pin"></form>')],
        ]
        for script in cases:
            with self.subTest(script=script):
                session, = self.scripted(script)
                with InhaCloud() as client:
                    result = client.login(ACCOUNT, PASSWORD)
                    self.assertEqual(result.status, LoginStatus.ADDITIONAL_AUTH)
                    self.assertIsNone(result.identity)
                self.assertEqual(len(session.adapter.requests), len(script))

    def test_mfa_redirect_cannot_disappear_into_later_success(self):
        session, = self.scripted([Page(FORM), Page(status=302, headers={"Location": "/auth/mfa/pin"}),
                                  Page("", status=302, headers={"Location": "/account"}), Page(IDENTITY)])
        with InhaCloud() as client:
            result = client.login(ACCOUNT, PASSWORD)
            self.assertEqual(result.status, LoginStatus.ADDITIONAL_AUTH)
            self.assertIsNone(result.identity)
        self.assertEqual(len(session.adapter.requests), 2)

    def test_encoded_and_normalized_mfa_targets_are_not_followed(self):
        for target in ("/auth/%6dfa/pin", "/%61uth/mfa/pin", "/auth/./mfa/pin", "/x/../auth/mfa/pin"):
            for stage in ("form", "redirect"):
                with self.subTest(target=target, stage=stage):
                    script = ([Page(FORM + f'<form action="{target}"></form>')] if stage == "form"
                              else [Page(FORM), Page(status=302, headers={"Location": target})])
                    session, = self.scripted(script)
                    with InhaCloud() as client:
                        self.assertEqual(client.login(ACCOUNT, PASSWORD).status, LoginStatus.ADDITIONAL_AUTH)
                        self.assertIsNone(client.fetch_login_info().identity)
                    self.assertEqual(len(session.adapter.requests), len(script))

    def test_nonstandard_wire_status_is_a_failure_and_invalidates_authentication(self):
        for status in (600, 999):
            for stage in ("landing", "post", "fetch"):
                with self.subTest(status=status, stage=stage):
                    script = ([Page(status=status)] if stage == "landing"
                              else [Page(FORM), Page(status=status)] if stage == "post"
                              else [Page(FORM), Page(IDENTITY), Page(status=status)])
                    session, = self.scripted(script)
                    with InhaCloud() as client:
                        result = client.login(ACCOUNT, PASSWORD)
                        if stage == "fetch":
                            self.assertTrue(result.success)
                            result = client.fetch_login_info()
                        self.assertEqual(result.status, LoginStatus.HTTP_ERROR)
                        self.assertIsNone(result.http_status)
                        self.assertIsNone(result.identity)
                        self.assertEqual(client.fetch_login_info().status, LoginStatus.NOT_AUTHENTICATED)
                        self.assertTrue(session.closed)

    def test_changed_login_form_never_submits_credentials(self):
        invalid_forms = [
            FORM.replace('method="POST"', 'method="GET"'),
            FORM.replace('name="_csrf"', 'name="csrf-changed"'),
            FORM.replace('value="synthetic-token"', 'value=""'),
            FORM.replace('value="inha.ac.kr"', 'value="other.ac.kr"'),
            FORM.replace('name="userid"', 'name="new-userid"'),
            FORM.replace('type="password"', 'type="text"'),
            FORM.replace('name="password"', 'name="password" disabled'),
            FORM.replace('</form>', '<input name="_csrf" value="extra"></form>'),
            FORM + FORM,
        ]
        for html in invalid_forms:
            with self.subTest(html=html):
                session, = self.scripted([Page(html)])
                with InhaCloud() as client:
                    self.assertEqual(client.login(ACCOUNT, PASSWORD).status, LoginStatus.PAGE_CHANGED)
                self.assertEqual([r.method for r in session.adapter.requests], ["GET"])

    def test_foreign_or_unsafe_credential_form_is_never_submitted(self):
        for target in ("https://example.test/auth/login", "http://cloud.inha.ac.kr/auth/login", "https://cloud.inha.ac.kr:444/auth/login", "https://u:p@cloud.inha.ac.kr/auth/login", "/auth/login?redirect=other"):
            with self.subTest(target=target):
                session, = self.scripted([Page(FORM.replace('/auth/login', target))])
                with InhaCloud() as client:
                    result = client.login(ACCOUNT, PASSWORD)
                    self.assertEqual(result.status, LoginStatus.UNSAFE_DESTINATION)
                self.assertEqual(len(session.adapter.requests), 1)

    def test_credentials_are_not_forwarded_to_external_redirect(self):
        for target in ("https://example.test/collect", "http://cloud.inha.ac.kr/collect", "https://cloud.inha.ac.kr:444/collect", "https://u:p@cloud.inha.ac.kr/collect", "https://cloud.inha.ac.kr:invalid/collect", "https://[cloud.inha.ac.kr/collect"):
            with self.subTest(target=target):
                session, = self.scripted([Page(FORM), Page(status=302, headers={"Location": target})])
                with InhaCloud() as client:
                    result = client.login(ACCOUNT, PASSWORD)
                    self.assertEqual(result.status, LoginStatus.UNSAFE_DESTINATION)
                    self.assertIsNone(result.identity)
                    self.assertTrue(session.closed)
                self.assertEqual(len(session.adapter.requests), 2)

    def test_redirect_bodies_are_not_eagerly_buffered(self):
        session, = self.scripted([Page("x" * (2 * 1024 * 1024), status=302, headers={"Location": "/t/inha.ac.kr"}), Page(FORM), Page(IDENTITY)])
        with InhaCloud() as client:
            self.assertTrue(client.login(ACCOUNT, PASSWORD).success)
        self.assertEqual(session.adapter.bodies[0].bytes_read, 0)

    def test_307_and_308_do_not_replay_post_even_on_same_host(self):
        for status in (307, 308):
            with self.subTest(status=status):
                session, = self.scripted([Page(FORM), Page(status=status, headers={"Location": "/auth/login"})])
                with InhaCloud() as client:
                    self.assertEqual(client.login(ACCOUNT, PASSWORD).status, LoginStatus.UNSAFE_DESTINATION)
                self.assertEqual(sum(r.method == "POST" for r in session.adapter.requests), 1)

    def test_post_redirect_to_get_drops_credentials(self):
        for status in (301, 302, 303):
            with self.subTest(status=status):
                session, = self.scripted([Page(status=302, headers={"Location": "/t/inha.ac.kr"}), Page(FORM),
                                          Page(status=status, headers={"Location": "/account"}), Page(IDENTITY)])
                with InhaCloud() as client:
                    self.assertTrue(client.login(ACCOUNT, PASSWORD).success)
                final_request = session.adapter.requests[-1]
                self.assertEqual(final_request.method, "GET")
                self.assertIsNone(final_request.body)
                self.assertNotIn(PASSWORD, final_request.url)
                self.assertEqual(sum(r.method == "POST" for r in session.adapter.requests), 1)

    def test_credential_get_redirects_are_bounded(self):
        session, = self.scripted([Page(status=302, headers={"Location": "/loop"}) for _ in range(10)])
        with InhaCloud() as client:
            result = client.login(ACCOUNT, PASSWORD)
            self.assertEqual(result.status, LoginStatus.PAGE_CHANGED)
        self.assertLess(len(session.adapter.requests), 10)
        self.assertFalse(any(r.method == "POST" for r in session.adapter.requests))

    def test_blank_post_has_one_confirmation_get_but_nonempty_unknown_page_does_not(self):
        for blank in (Page("   "), Page("", status=204)):
            with self.subTest(blank=blank):
                session, = self.scripted([Page(FORM), blank, Page(IDENTITY)])
                with InhaCloud() as client:
                    self.assertTrue(client.login(ACCOUNT, PASSWORD).success)
                self.assertEqual([r.method for r in session.adapter.requests], ["GET", "POST", "GET"])
        session, = self.scripted([Page(FORM), Page("<html>Unrecognized nonempty response</html>"), Page(IDENTITY)])
        with InhaCloud() as client:
            self.assertEqual(client.login(ACCOUNT, PASSWORD).status, LoginStatus.PAGE_CHANGED)
        self.assertEqual(len(session.adapter.requests), 2)

    def test_blank_confirmation_does_not_loop(self):
        session, = self.scripted([Page(FORM), Page(""), Page("")])
        with InhaCloud() as client:
            self.assertEqual(client.login(ACCOUNT, PASSWORD).status, LoginStatus.PAGE_CHANGED)
        self.assertEqual(len(session.adapter.requests), 3)

    def test_rate_limit_server_error_and_http_error_are_distinct_and_never_retried(self):
        for code, expected in ((429, LoginStatus.RATE_LIMITED), (500, LoginStatus.SERVICE_UNAVAILABLE),
                               (503, LoginStatus.SERVICE_UNAVAILABLE), (401, LoginStatus.REJECTED),
                               (403, LoginStatus.REJECTED), (404, LoginStatus.HTTP_ERROR)):
            with self.subTest(code=code):
                session, = self.scripted([Page(FORM), Page(IDENTITY, code, {"Retry-After": "10"})])
                with InhaCloud() as client:
                    result = client.login(ACCOUNT, PASSWORD)
                    self.assertEqual((result.status, result.http_status, result.identity), (expected, code, None))
                    self.assertEqual(client.fetch_login_info().status, LoginStatus.NOT_AUTHENTICATED)
                self.assertEqual(sum(r.method == "POST" for r in session.adapter.requests), 1)
                self.assertEqual(len(session.adapter.requests), 2)

    def test_connection_tls_and_timeout_failures_never_echo_secrets_or_retry(self):
        for exception in (requests.Timeout(PASSWORD), requests.ConnectionError(PASSWORD), requests.exceptions.SSLError(PASSWORD)):
            with self.subTest(exception=type(exception)):
                session, = self.scripted([Page(FORM), exception])
                with InhaCloud() as client:
                    result = client.login(ACCOUNT, PASSWORD)
                    self.assertEqual(result.status, LoginStatus.NETWORK_ERROR)
                    self.assertNotIn(PASSWORD, result.message + repr(result))
                    self.assertIsNone(result.identity)
                self.assertTrue(session.closed)
                self.assertEqual(len(session.adapter.requests), 2)

    def test_non_html_async_and_oversized_identity_pages_are_not_success(self):
        for bad in (Page(IDENTITY, headers={"Content-Type": "application/json"}), Page(IDENTITY, status=202), Page("", status=202),
                    Page(IDENTITY + "x" * (1024 * 1024))):
            with self.subTest(status=bad.status, headers=bad.headers):
                self.scripted([Page(FORM), bad])
                with InhaCloud() as client:
                    self.assertEqual(client.login(ACCOUNT, PASSWORD).status, LoginStatus.PAGE_CHANGED)

    def test_each_login_uses_fresh_session_and_invalid_input_invalidates_old_login(self):
        first, second = self.scripted([Page(FORM), Page(IDENTITY)], [Page(FORM), Page(IDENTITY)])
        with InhaCloud() as client:
            earlier = client.login(ACCOUNT, PASSWORD)
            first.cookies.set("old-account-cookie", "synthetic-value")
            self.assertTrue(client.login(ACCOUNT, PASSWORD).success)
            self.assertTrue(first.closed)
            self.assertFalse(first.cookies)
            self.assertNotIn("old-account-cookie", second.adapter.requests[0].headers.get("Cookie", ""))
            self.assertEqual(client.login("", PASSWORD).status, LoginStatus.INVALID_INPUT)
            self.assertEqual(client.fetch_login_info().status, LoginStatus.NOT_AUTHENTICATED)
            self.assertTrue(earlier.success)  # immutable prior observation is not a live session
        self.assertTrue(second.closed)

    def test_fetch_failure_or_account_change_invalidates_previous_session(self):
        for after in (Page(IDENTITY.replace(ACCOUNT, "other-account")), requests.Timeout(PASSWORD), Page(FORM)):
            with self.subTest(after=type(after)):
                session, = self.scripted([Page(FORM), Page(IDENTITY), after])
                with InhaCloud() as client:
                    self.assertTrue(client.login(ACCOUNT, PASSWORD).success)
                    result = client.fetch_login_info()
                    self.assertFalse(result.success)
                    self.assertIsNone(result.identity)
                    self.assertEqual(client.fetch_login_info().status, LoginStatus.NOT_AUTHENTICATED)
                self.assertEqual(len(session.adapter.requests), 3)
                self.assertTrue(session.closed)

    def test_interrupted_or_unexpected_login_closes_session_before_propagating(self):
        for failure in (KeyboardInterrupt(), RuntimeError("synthetic transport bug")):
            with self.subTest(failure=type(failure).__name__):
                session, = self.scripted([Page(FORM), failure])
                client = InhaCloud()
                try:
                    with self.assertRaises(type(failure)):
                        client.login(ACCOUNT, PASSWORD)
                    self.assertTrue(session.closed)
                    self.assertEqual(client.fetch_login_info().status, LoginStatus.NOT_AUTHENTICATED)
                finally:
                    client.close()

    def test_interrupted_fetch_discards_previous_authentication(self):
        session, = self.scripted([Page(FORM), Page(IDENTITY), KeyboardInterrupt()])
        client = InhaCloud()
        try:
            self.assertTrue(client.login(ACCOUNT, PASSWORD).success)
            with self.assertRaises(KeyboardInterrupt):
                client.fetch_login_info()
            self.assertTrue(session.closed)
            self.assertEqual(client.fetch_login_info().status, LoginStatus.NOT_AUTHENTICATED)
        finally:
            client.close()

    def test_fetch_without_login_and_after_close_perform_no_network(self):
        with patch("inha_cloud.inha_cloud._Session") as factory:
            client = InhaCloud()
            self.assertEqual(client.fetch_login_info().status, LoginStatus.NOT_AUTHENTICATED)
            client.close()
            client.close()
            self.assertEqual(client.fetch_login_info().status, LoginStatus.CLOSED)
            self.assertEqual(client.login(ACCOUNT, PASSWORD).status, LoginStatus.CLOSED)
            factory.assert_not_called()

    def test_invalid_inputs_do_not_create_a_session(self):
        with patch("inha_cloud.inha_cloud._Session") as factory:
            with InhaCloud() as client:
                for username, password in ((None, PASSWORD), ("  ", PASSWORD), (ACCOUNT, ""), (ACCOUNT, None)):
                    with self.subTest(username=username):
                        self.assertEqual(client.login(username, password).status, LoginStatus.INVALID_INPUT)
            factory.assert_not_called()

    def test_invalid_timeouts_rejected_before_network(self):
        for timeout in (0, -1, math.inf, math.nan, True, "15", 10**1000):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    InhaCloud(timeout=timeout)

    def test_no_ambient_netrc_proxy_credentials_and_tls_is_verified(self):
        session, = self.scripted([Page(FORM), Page(IDENTITY)])
        with tempfile.TemporaryDirectory(prefix="inha-ambient-") as directory:
            netrc = Path(directory) / "synthetic.netrc"
            netrc.write_text("machine cloud.inha.ac.kr login ambient password synthetic-ambient-secret\n")
            netrc.chmod(0o600)
            environment = {
                "NETRC": str(netrc),
                "HTTPS_PROXY": "http://example.test:8888",
                "HTTP_PROXY": "http://example.test:8888",
                "REQUESTS_CA_BUNDLE": str(Path(directory) / "nonexistent-ca.pem"),
            }
            with patch.dict("os.environ", environment):
                with InhaCloud() as client:
                    self.assertTrue(client.login(ACCOUNT, PASSWORD).success)
        self.assertTrue(all(options['verify'] is True and not options['proxies'] for options in session.adapter.transport))
        self.assertFalse(any('Authorization' in request.headers for request in session.adapter.requests))
        self.assertFalse(session.trust_env)

    def test_hidden_unrelated_fields_do_not_become_credentials(self):
        html = FORM.replace('</form>', '<input type="hidden" name="unexpected" value="do-not-send"></form>')
        session, = self.scripted([Page(html), Page(IDENTITY)])
        with InhaCloud() as client:
            self.assertTrue(client.login(ACCOUNT, PASSWORD).success)
        submitted = parse_qs(session.adapter.requests[-1].body)
        self.assertNotIn('unexpected', submitted)


class ResultTests(unittest.TestCase):
    def test_failure_never_carries_identity_and_success_requires_it(self):
        identity = Identity(ACCOUNT, 'Synthetic')
        with self.assertRaises(ValueError):
            LoginResult(LoginStatus.SUCCESS)
        with self.assertRaises(ValueError):
            LoginResult(LoginStatus.REJECTED, identity)
        with self.assertRaises(ValueError):
            Identity('', 'Synthetic')
        result = LoginResult(LoginStatus.SUCCESS, identity, 200)
        with self.assertRaises(FrozenInstanceError):
            result.identity.account_id = 'another-account'


if __name__ == '__main__':
    unittest.main()
