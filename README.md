# INHA Login Fetcher

This project is a Python script that logs in to the Inha University site, checks the login status, and retrieves the user's name and student ID.

## Features

- Login to Inha University Cloud (https://cloud.inha.ac.kr)
- Fetch student name and student ID
- Support for CSRF protection
- CLI interface and environment variable support

## Installation

### From PyPI

``` sh
$ pip install inha-cloud
```

### From Source

1. Clone the repository:
``` sh
$ git clone https://github.com/inha-fc/inha-login-fetcher.git
$ cd inha-login-fetcher
```

2. Install the necessary packages:
``` sh
$ pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root and enter your credentials:

``` env
INHA_USERNAME=your_username
INHA_PASSWORD=your_password
```

## Usage

### CLI

You can run the script directly:

``` sh
$ python main.py
```

Or provide credentials as arguments (this overrides `.env`):

``` sh
$ python main.py -u your_username -p your_password
```

### Library Example

``` python
from inha_cloud.inha_cloud import InhaCloud

def main():
    # Instantiate an InhaCloud object (loads from .env by default)
    inha = InhaCloud()

    # Login (returns True/False)
    if not inha.login():
        print("Login failed.")
        return

    # Fetch login information
    login_info = inha.fetch_login_info()
    if login_info:
        print(f"Name: {login_info['name']}")
        print(f"Student ID: {login_info['student_id']}")

if __name__ == '__main__':
    main()
```

## License

This project is licensed under the terms of the MIT license. See the [LICENSE](/LICENSE) file for details.
