"""인증 정보를 출력하지 않는 로컬 학교 계정 검증 도구."""

import argparse
from getpass import getpass

from inha_cloud.inha_cloud import InhaCloud


def main():
    parser = argparse.ArgumentParser(description="인하대학교 계정 소유 확인")
    parser.add_argument("-u", "--username", help="학교 계정 아이디")
    parser.add_argument("--env", action="store_true", help="환경 변수와 .env 사용")
    parser.add_argument("--timeout", type=float, default=15, help="요청 제한 시간(초)")
    args = parser.parse_args()
    try:
        with InhaCloud(username=args.username, load_env=args.env,
                       timeout=args.timeout) as client:
            username = client.username or input("학교 계정 아이디: ").strip()
            password = client.password or getpass("학교 계정 비밀번호: ")
            try:
                success = client.login(username=username, password=password)
            finally:
                password = None
            print(client.message)
            print("결과 코드: " + client.status.value)
            return 0 if success else 1
    except (ValueError, EOFError):
        print("입력 또는 인증 화면을 확인할 수 없습니다.")
        return 2
    except KeyboardInterrupt:
        print("인증을 취소했습니다.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
