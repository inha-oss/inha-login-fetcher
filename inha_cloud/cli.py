"""인증 정보와 신원 정보를 출력하지 않는 학교 계정 확인 명령줄 도구."""

import argparse
import getpass
import json
import os
import sys
import warnings

from inha_cloud import InhaCloud, LoginResult, LoginStatus
from ._version import __version__

_PROG = "inha-login-fetcher"
_EXIT_CODES = {
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
_EXIT_INTERRUPTED = 130
_EXIT_UNEXPECTED = 70


class _MissingInput(Exception):
    """대화형으로 안전하게 받을 수 없는 입력."""


class _SafeParser(argparse.ArgumentParser):
    """잘못된 인자를 오류 문구에 되풀이하지 않는 파서."""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write(self.prog + ": 옵션 또는 값이 올바르지 않습니다. --help를 확인하세요.\n")
        raise SystemExit(2)




def _parser():
    parser = _SafeParser(
        prog=_PROG, allow_abbrev=False,
        description="인하대학교 계정 소유 확인. 비밀번호는 옵션으로 받지 않습니다.")
    parser.add_argument("-u", "--username", help="학교 계정 아이디")
    parser.add_argument(
        "--env", action="store_true",
        help="현재 프로세스의 INHA_USERNAME, INHA_PASSWORD 환경 변수를 사용 (.env 파일은 읽지 않음)")
    parser.add_argument("--timeout", type=float, default=15, help="요청 제한 시간(초)")
    parser.add_argument("--json", action="store_true", help="status, message, http_status만 JSON으로 출력")
    parser.add_argument("--version", action="version", version=_PROG + " " + __version__)
    return parser


def _is_interactive():
    try:
        if sys.stdin is None or not sys.stdin.isatty():
            return False
        if os.name == "nt":
            # Windows isatty() also accepts NUL, which cannot supply getpass input.
            import ctypes
            from ctypes import wintypes
            import msvcrt

            get_console_mode = ctypes.WinDLL("kernel32", use_last_error=True).GetConsoleMode
            get_console_mode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            get_console_mode.restype = wintypes.BOOL
            mode = wintypes.DWORD()
            handle = msvcrt.get_osfhandle(sys.stdin.fileno())
            return bool(get_console_mode(handle, ctypes.byref(mode)))
        return True
    except (OSError, ValueError):
        return False


def _prompt_username():
    sys.stderr.write("학교 계정 아이디: ")
    sys.stderr.flush()
    line = sys.stdin.readline()
    if not line:
        raise _MissingInput
    return line.strip()


def _prompt_password():
    # getpass가 터미널 에코를 끌 수 없으면 비밀번호가 보이는 대체 입력으로 넘어가므로 거부한다.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass("학교 계정 비밀번호: ")
        except (EOFError, getpass.GetPassWarning):
            raise _MissingInput from None


def _credentials(args):
    username = args.username
    password = None
    if args.env:
        if username is None:
            username = os.environ.get("INHA_USERNAME")
        password = os.environ.get("INHA_PASSWORD")
    if username is not None and not username.strip():
        username = None
    if not password:
        password = None
    if username is None or password is None:
        if not _is_interactive():
            raise _MissingInput
        if username is None:
            username = _prompt_username()
        if password is None:
            password = _prompt_password()
    return username, password


def _authenticate(args):
    try:
        client = InhaCloud(timeout=args.timeout)
    except ValueError:
        return LoginResult(LoginStatus.INVALID_INPUT)
    try:
        try:
            username, password = _credentials(args)
        except _MissingInput:
            return LoginResult(LoginStatus.INVALID_INPUT)
        return client.login(username, password)
    finally:
        client.close()


def _emit(result, as_json):
    if as_json:
        # ASCII 이스케이프라서 어떤 콘솔 인코딩에서도 유효한 JSON이 출력된다.
        payload = {"status": result.status.value, "message": result.message,
                   "http_status": result.http_status}
        print(json.dumps(payload))
    else:
        print(result.message)
        print("결과 코드: " + result.status.value)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    try:
        args = _parser().parse_args(argv)
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else 0
    try:
        result = _authenticate(args)
    except KeyboardInterrupt:
        sys.stderr.write("인증을 취소했습니다.\n")
        return _EXIT_INTERRUPTED
    except Exception:
        sys.stderr.write("예기치 않은 오류로 인증을 완료하지 못했습니다.\n")
        return _EXIT_UNEXPECTED
    _emit(result, args.json)
    return _EXIT_CODES[result.status]
