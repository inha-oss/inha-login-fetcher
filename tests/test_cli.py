"""명령줄 경계에서 비밀 노출, 종료 코드, 네트워크 이전 실패를 검증한다. 학교에는 요청하지 않는다."""

import contextlib
import getpass
import io
import json
import os
import subprocess
import sys
import unittest
import warnings
from pathlib import Path
from unittest.mock import Mock, patch

from _network import sitecustomize as _network_guard

from inha_cloud import Identity, LoginResult, LoginStatus
from inha_cloud import cli

ROOT = Path(__file__).resolve().parent.parent
SECRET = "hunter2-비밀"
ACCOUNT = "test-account-id"
DISPLAY_NAME = "표시이름-노출금지"


class Stdin(io.StringIO):
    def __init__(self, text="", tty=False):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


class CliTestCase(unittest.TestCase):
    def setUp(self):
        guard = patch("requests.adapters.HTTPAdapter.send",
                      side_effect=AssertionError("테스트에서 네트워크 사용"))
        guard.start()
        self.addCleanup(guard.stop)

    def run_cli(self, argv, env=None, stdin="", tty=False, result=None, login=None, getpass_value=None):
        """클라이언트를 대체해 CLI를 실행하고 (종료 코드, stdout, stderr, 클라이언트)를 돌려준다."""
        client = Mock()
        client.login = Mock(side_effect=login) if login else Mock(
            return_value=result if result is not None else LoginResult(LoginStatus.SUCCESS, Identity(ACCOUNT, DISPLAY_NAME), 200))
        out, err = io.StringIO(), io.StringIO()
        environ = {k: v for k, v in os.environ.items() if not k.startswith("INHA_")}
        environ.update(env or {})
        prompt = patch("getpass.getpass", return_value=getpass_value) if not isinstance(
            getpass_value, BaseException) else patch("getpass.getpass", side_effect=getpass_value)
        with patch.dict(os.environ, environ, clear=True), patch("sys.stdin", Stdin(stdin, tty)), \
                patch("inha_cloud.cli.InhaCloud", return_value=client), prompt, \
                patch("inha_cloud.cli._is_interactive", return_value=tty), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue(), client

    def assert_no_secret(self, *streams):
        for text in streams:
            for private in (SECRET, ACCOUNT, DISPLAY_NAME):
                self.assertNotIn(private, text)


class ExitCodeTests(CliTestCase):
    EXPECTED = {
        LoginStatus.SUCCESS: 0,
        LoginStatus.REJECTED: 1,
        LoginStatus.NOT_AUTHENTICATED: 1,
        LoginStatus.INVALID_INPUT: 2,
        LoginStatus.PAGE_CHANGED: 2,
        LoginStatus.UNSAFE_DESTINATION: 2,
        LoginStatus.IDENTITY_MISMATCH: 2,
        LoginStatus.HTTP_ERROR: 2,
        LoginStatus.CLOSED: 2,
        LoginStatus.ADDITIONAL_AUTH: 3,
        LoginStatus.NETWORK_ERROR: 4,
        LoginStatus.RATE_LIMITED: 4,
        LoginStatus.SERVICE_UNAVAILABLE: 4,
    }

    def test_모든_상태가_계약된_종료_코드를_가진다(self):
        self.assertEqual(set(self.EXPECTED), set(LoginStatus))
        for status, expected in self.EXPECTED.items():
            identity = Identity(ACCOUNT, DISPLAY_NAME) if status is LoginStatus.SUCCESS else None
            with self.subTest(status=status):
                code, out, err, _ = self.run_cli(
                    ["-u", ACCOUNT, "--env"], env={"INHA_PASSWORD": SECRET},
                    result=LoginResult(status, identity, 418))
                self.assertEqual(code, expected)
                self.assertIn(status.value, out)
                self.assert_no_secret(out, err)

    def test_json은_status_message_http_status만_담는다(self):
        code, out, err, _ = self.run_cli(
            ["-u", ACCOUNT, "--env", "--json"], env={"INHA_PASSWORD": SECRET},
            result=LoginResult(LoginStatus.SUCCESS, Identity(ACCOUNT, DISPLAY_NAME), 200))
        self.assertEqual(code, 0)
        self.assert_no_secret(out, err)
        payload = json.loads(out)
        self.assertEqual(set(payload), {"status", "message", "http_status"})
        self.assertEqual((payload["status"], payload["http_status"]), ("success", 200))

    def test_json_실패도_http_status를_null로_유지한다(self):
        code, out, _, _ = self.run_cli(
            ["-u", ACCOUNT, "--env", "--json"], env={"INHA_PASSWORD": SECRET},
            result=LoginResult(LoginStatus.NETWORK_ERROR))
        self.assertEqual(code, 4)
        self.assertEqual(json.loads(out)["http_status"], None)

    def test_예상하지_못한_예외는_원문을_출력하지_않는다(self):
        code, out, err, _ = self.run_cli(
            ["-u", ACCOUNT, "--env", "--json"], env={"INHA_PASSWORD": SECRET},
            login=RuntimeError("password=" + SECRET))
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assert_no_secret(out, err)
        self.assertNotIn("Traceback", err)

    def test_취소는_130이고_출력에_비밀이_없다(self):
        code, out, err, _ = self.run_cli(
            ["-u", ACCOUNT, "--env"], env={"INHA_PASSWORD": SECRET}, login=KeyboardInterrupt())
        self.assertEqual(code, 130)
        self.assert_no_secret(out, err)
        self.assertNotIn("Traceback", err)

    def test_완료하면_클라이언트를_닫는다(self):
        for login in (None, RuntimeError("x"), KeyboardInterrupt()):
            with self.subTest(login=login):
                _, _, _, client = self.run_cli(
                    ["-u", ACCOUNT, "--env"], env={"INHA_PASSWORD": SECRET}, login=login)
                client.close.assert_called_once_with()


class ArgumentTests(CliTestCase):
    def test_잘못된_인자는_입력한_값을_되풀이하지_않는다(self):
        for argv in (
            ["--password", SECRET],
            ["--password=" + SECRET],
            ["--passwor=" + SECRET],
            ["-p", SECRET],
            [SECRET],
            ["--timeout", SECRET],
            ["--timeout=" + SECRET],
            ["--json=" + SECRET],
            ["--username"],
            ["--" + SECRET],
        ):
            with self.subTest(argv=argv):
                code, out, err, client = self.run_cli(argv, env={"INHA_PASSWORD": SECRET}, tty=True,
                                                      getpass_value=SECRET)
                self.assertEqual(code, 2)
                self.assert_no_secret(out, err)
                self.assertNotIn("Traceback", err)
                client.login.assert_not_called()


    def test_유효하지_않은_timeout은_입력_전에_invalid_input이다(self):
        out, err = io.StringIO(), io.StringIO()
        for value in ("0", "-1", "nan", "inf"):
            with self.subTest(timeout=value), patch("getpass.getpass") as prompt, \
                    patch("sys.stdin", Stdin("", True)), contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(err):
                code = cli.main(["-u", ACCOUNT, "--timeout", value, "--json"])
                self.assertEqual(code, 2)
                prompt.assert_not_called()
        self.assertEqual(json.loads(out.getvalue().splitlines()[0])["status"], "invalid_input")


class CredentialSourceTests(CliTestCase):
    def test_env_옵션_없이는_환경_변수를_읽지_않는다(self):
        code, out, err, client = self.run_cli(
            ["--json"], env={"INHA_USERNAME": ACCOUNT, "INHA_PASSWORD": SECRET})
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["status"], "invalid_input")
        self.assert_no_secret(out, err)
        client.login.assert_not_called()

    def test_env는_비밀번호_공백을_보존해_인증한다(self):
        password = "  " + SECRET + "  "
        def authenticate(username, secret):
            status = LoginStatus.SUCCESS if username == ACCOUNT and secret == password else LoginStatus.REJECTED
            return LoginResult(status, Identity(ACCOUNT, DISPLAY_NAME) if status is LoginStatus.SUCCESS else None)
        code, out, err, _ = self.run_cli(
            ["--env"], env={"INHA_USERNAME": ACCOUNT, "INHA_PASSWORD": password}, login=authenticate)
        self.assertEqual(code, 0)
        self.assert_no_secret(out, err)

    def test_명시한_username이_환경_변수보다_우선한다(self):
        def authenticate(username, secret):
            status = LoginStatus.SUCCESS if username == ACCOUNT and secret == SECRET else LoginStatus.REJECTED
            return LoginResult(status, Identity(ACCOUNT, DISPLAY_NAME) if status is LoginStatus.SUCCESS else None)
        code, _, _, _ = self.run_cli(
            ["--env", "-u", ACCOUNT], env={"INHA_USERNAME": "other", "INHA_PASSWORD": SECRET}, login=authenticate)
        self.assertEqual(code, 0)

    def test_터미널에서는_숨긴_비밀번호로_인증한다(self):
        def authenticate(username, secret):
            status = LoginStatus.SUCCESS if username == ACCOUNT and secret == SECRET else LoginStatus.REJECTED
            return LoginResult(status, Identity(ACCOUNT, DISPLAY_NAME) if status is LoginStatus.SUCCESS else None)
        code, out, err, _ = self.run_cli(
            ["-u", ACCOUNT], tty=True, getpass_value=SECRET, login=authenticate)
        self.assertEqual(code, 0)
        self.assert_no_secret(out, err)

    def test_터미널에서_빠진_아이디는_stdout_오염_없이_묻는다(self):
        def authenticate(username, secret):
            status = LoginStatus.SUCCESS if username == ACCOUNT and secret == SECRET else LoginStatus.REJECTED
            return LoginResult(status, Identity(ACCOUNT, DISPLAY_NAME) if status is LoginStatus.SUCCESS else None)
        code, out, err, _ = self.run_cli(
            ["--json"], stdin=ACCOUNT + "\n", tty=True, getpass_value=SECRET, login=authenticate)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["status"], "success")
        self.assertNotIn(SECRET, err)


class BeforeNetworkTests(CliTestCase):
    def assert_invalid_before_network(self, *args, **kwargs):
        code, out, err, client = self.run_cli(*args, **kwargs)
        self.assertEqual(code, 2)
        self.assertIn("invalid_input", out)
        self.assert_no_secret(out, err)
        self.assertNotIn("Traceback", err)
        client.login.assert_not_called()

    def test_터미널이_아니면_빠진_인증_정보로_실패한다(self):
        self.assert_invalid_before_network([])
        self.assert_invalid_before_network(["-u", ACCOUNT])
        self.assert_invalid_before_network(["--env"], env={"INHA_USERNAME": ACCOUNT})
        self.assert_invalid_before_network(["--env"], env={"INHA_PASSWORD": SECRET})
        self.assert_invalid_before_network(["--env"], env={"INHA_USERNAME": " ", "INHA_PASSWORD": SECRET})

    def test_터미널이_아니면_stdin의_비밀번호를_읽지_않는다(self):
        self.assert_invalid_before_network(["-u", ACCOUNT], stdin=SECRET + "\n")
        self.assert_invalid_before_network([], stdin=ACCOUNT + "\n" + SECRET + "\n")

    def test_getpass가_에코_대체_입력을_요구하면_거부한다(self):
        def echoing_fallback(*_args, **_kwargs):
            warnings.warn("Can not control echo on the terminal.", getpass.GetPassWarning)
            raise AssertionError("에코되는 입력으로 계속 진행됨")

        with patch("getpass.getpass", side_effect=echoing_fallback), patch("sys.stdin", Stdin("", True)), \
                patch("inha_cloud.cli.InhaCloud") as factory, \
                patch("inha_cloud.cli._is_interactive", return_value=True), \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            code = cli.main(["-u", ACCOUNT])
        self.assertEqual(code, 2)
        self.assertIn("invalid_input", out.getvalue())
        self.assertNotIn("Traceback", err.getvalue())
        factory.return_value.login.assert_not_called()

    def test_비밀번호_입력_EOF는_안전하게_실패한다(self):
        self.assert_invalid_before_network(["-u", ACCOUNT], tty=True, getpass_value=EOFError())

    def test_아이디_입력_EOF는_안전하게_실패한다(self):
        self.assert_invalid_before_network([], tty=True, stdin="")


class EntryPointTests(unittest.TestCase):
    def run_module(self, *args, **env):
        environment = {k: v for k, v in os.environ.items() if not k.startswith("INHA_")}
        environment.update(env)
        guard_path = str(ROOT / "tests" / "_network")
        environment["PYTHONPATH"] = guard_path + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
        return subprocess.run(
            [sys.executable, "-m", "inha_cloud", *args], cwd=ROOT, env=environment,
            stdin=subprocess.DEVNULL, capture_output=True, timeout=30)

    def test_python_m이_네트워크_없이_누락된_인증_정보를_거부한다(self):
        done = self.run_module("--env", "--json", INHA_USERNAME=ACCOUNT)
        self.assertEqual(done.returncode, 2)
        self.assertEqual(json.loads(done.stdout)["status"], "invalid_input")
        self.assertNotIn(ACCOUNT.encode(), done.stdout + done.stderr)

    def test_python_m이_잘못된_옵션_값을_되풀이하지_않는다(self):
        done = self.run_module("--password=" + SECRET)
        self.assertEqual(done.returncode, 2)
        self.assertNotIn(SECRET.encode(), done.stdout + done.stderr)
        self.assertNotIn(b"Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()
