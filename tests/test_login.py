"""학교에 요청하지 않고 인증 경계와 정보 노출을 검증한다."""

import unittest
from unittest.mock import Mock

import requests

from inha_cloud.inha_cloud import InhaCloud, LoginStatus

FORM = '''<form action="/auth/login"><input name="_csrf" type="hidden" value="token">
<input type="hidden" name="loginDomain" value="inha.ac.kr">
<input type="hidden" name="RelayState" value="context"></form>'''
IDENTITY = '<div class="loginHeader" data-userid="example-account">예시 사용자</div>'


def response(html, url="https://cloud.inha.ac.kr/t/inha.ac.kr", status=200, headers=None):
    result = Mock(text=html, url=url, status_code=status, headers=headers or {})
    return result


class LoginTests(unittest.TestCase):
    def test_동일_호스트의_상대_이동을_따른다(self):
        client = self.client(response(FORM), response("", status=302,
                             headers={"Location": "/account"}), response(IDENTITY))
        self.assertTrue(client.login())
        call = client._session.request.call_args
        self.assertEqual(call.args, ("GET", "https://cloud.inha.ac.kr/account"))
        self.assertIsNone(call.kwargs["data"])

    def test_빈_로그인_응답은_홈에서_한번_확인한다(self):
        client = self.client(response(FORM), response(""), response(IDENTITY))
        self.assertTrue(client.login())
        self.assertEqual(client._session.request.call_count, 3)

    def test_빈_계정_id를_인증_성공으로_처리하지_않는다(self):
        client = self.client(response(FORM), response('<div class="loginHeader" data-userid=""></div>'), response(""))
        self.assertFalse(client.login())
        self.assertEqual(client.status, LoginStatus.PAGE_CHANGED)

    def client(self, *pages):
        client = InhaCloud("example-account", "test-secret")
        client._session.request = Mock(side_effect=pages)
        return client

    def test_인증된_계정만_성공하고_비밀번호를_정리한다(self):
        client = self.client(response(FORM), response(IDENTITY))
        client._session.cookies.set("previous", "session")
        self.assertTrue(client.login())
        self.assertEqual(client.account_id, "example-account")
        self.assertEqual(client.name, "예시 사용자")
        self.assertIsNone(client.password)
        self.assertFalse(client._session.cookies)
        call = client._session.request.call_args
        self.assertEqual(call.kwargs["timeout"], 15)
        self.assertFalse(call.kwargs["allow_redirects"])

    def test_로그인_화면은_인증_속성이_있어도_실패한다(self):
        client = self.client(response(FORM), response(FORM + IDENTITY))
        self.assertFalse(client.login())
        self.assertEqual(client.status, LoginStatus.REJECTED)
        self.assertIsNone(client.account_id)

    def test_추가_인증을_가입_성공으로_처리하지_않는다(self):
        client = self.client(response(FORM), response(IDENTITY, "https://cloud.inha.ac.kr/auth/mfa/login"))
        self.assertFalse(client.login())
        self.assertEqual(client.status, LoginStatus.ADDITIONAL_AUTH)
        self.assertEqual(client._session.request.call_count, 2)

    def test_화면_변경은_인증_실패와_구분한다(self):
        client = self.client(response("<html>변경된 페이지</html>"))
        self.assertFalse(client.login())
        self.assertEqual(client.status, LoginStatus.PAGE_CHANGED)
        self.assertEqual(client._session.request.call_count, 1)

    def test_네트워크_오류에_비밀번호를_포함하지_않는다(self):
        client = self.client(requests.Timeout("test-secret"))
        self.assertFalse(client.login())
        self.assertEqual(client.status, LoginStatus.NETWORK_ERROR)
        self.assertNotIn("test-secret", client.message)
        self.assertIsNone(client.password)

    def test_외부_호스트로_인증_정보를_전송하지_않는다(self):
        client = self.client(response(FORM), response("", status=307,
                             headers={"Location": "https://example.org/collect"}))
        with self.assertRaises(ValueError):
            client.login()
        self.assertEqual(client._session.request.call_count, 2)
        self.assertIsNone(client.password)

    def test_숨김_필드와_csrf를_현재_양식에서_가져온다(self):
        client = InhaCloud("example", "secret")
        observed = {}
        def request(method, url, **kwargs):
            if method == "POST":
                observed.update(kwargs["data"])
                return response(IDENTITY)
            return response(FORM)
        client._session.request = Mock(side_effect=request)
        self.assertTrue(client.login())
        self.assertEqual(observed["RelayState"], "context")
        self.assertEqual(observed["_csrf"], "token")

    def test_재인증_실패시_이전_사용자_정보를_남기지_않는다(self):
        client = self.client(response(FORM), response(IDENTITY), response(FORM), response(FORM))
        self.assertTrue(client.login())
        self.assertFalse(client.login(password="new-secret"))
        self.assertIsNone(client.account_id)

    def test_조회_실패시_기존_정보를_정리한다(self):
        client = self.client(response(FORM), response(IDENTITY), requests.Timeout())
        self.assertTrue(client.login())
        self.assertIsNone(client.fetch_login_info())
        self.assertIsNone(client.account_id)

    def test_컨텍스트_종료시_쿠키와_개인정보를_정리한다(self):
        client = self.client(response(FORM), response(IDENTITY))
        with client:
            self.assertTrue(client.login())
            client._session.cookies.set("session", "value")
        self.assertFalse(client._session.cookies)
        self.assertIsNone(client.account_id)


if __name__ == "__main__":
    unittest.main()
