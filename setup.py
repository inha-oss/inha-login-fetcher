from setuptools import setup, find_packages

setup(
    name="inha_cloud",
    version="0.3.0",
    packages=find_packages(),
    description="인하대학교 계정 소유 확인을 위한 로그인 클라이언트",
    author="Lee Jongyoung",
    author_email="leejongyoung98@inha.edu",
    url="https://github.com/inha-oss/inha-login-fetcher",
    python_requires=">=3.9",
    install_requires=[
        'python-dotenv',
        'requests',
        'beautifulsoup4',
    ],
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
    ],
)
