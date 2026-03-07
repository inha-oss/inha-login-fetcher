# 인하대학교 로그인 정보 가져오기

이 프로젝트는 파이썬을 사용하여 인하대학교 사이트에 로그인을 확인하고 이름과 학번을 가져오는 스크립트입니다.

## 주요 기능

- 인하대학교 클라우드(https://cloud.inha.ac.kr) 로그인
- 학생 이름 및 학번 조회
- CSRF 보안 대응
- CLI 인터페이스 및 환경 변수 지원

## 설치 방법

### PyPI 이용

``` sh
$ pip install inha-cloud
```

### 소스코드 이용

1. 저장소를 클론합니다:
``` sh
$ git clone https://github.com/inha-fc/inha-login-fetcher.git
$ cd inha-login-fetcher
```

2. 필요한 패키지를 설치합니다:
``` sh
$ pip install -r requirements.txt
```

## 설정

프로젝트 루트 디렉토리에 `.env` 파일을 생성하고 다음과 같이 정보를 입력하세요:

``` env
INHA_USERNAME=사용자_아이디
INHA_PASSWORD=비밀번호
```

## 사용 방법

### CLI 실행

스크립트를 직접 실행할 수 있습니다:

``` sh
$ python main.py
```

인자를 통해 아이디와 비밀번호를 직접 전달할 수도 있습니다 (이 경우 `.env` 설정보다 우선합니다):

``` sh
$ python main.py -u 아이디 -p 비밀번호
```

### 라이브러리 사용 예시

``` python
from inha_cloud.inha_cloud import InhaCloud

def main():
    # InhaCloud 객체 생성 (기본적으로 .env 파일에서 정보를 읽어옵니다)
    inha = InhaCloud()

    # 로그인 실행 (성공 시 True, 실패 시 False 반환)
    if not inha.login():
        print("로그인에 실패하였습니다.")
        return

    # 로그인 정보 가져오기
    login_info = inha.fetch_login_info()
    if login_info:
        print(f"이름: {login_info['name']}")
        print(f"학번: {login_info['student_id']}")

if __name__ == '__main__':
    main()
```

## 라이선스

이 프로젝트는 MIT 라이선스 조건에 따라 사용이 가능합니다. 자세한 내용은 [LICENSE](/LICENSE) 파일을 확인해주세요.
