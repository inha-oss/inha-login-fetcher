import argparse
import sys
from inha_cloud.inha_cloud import InhaCloud

def main():
    parser = argparse.ArgumentParser(description="Inha University Login Fetcher")
    parser.add_argument("-u", "--username", help="Inha Portal ID")
    parser.add_argument("-p", "--password", help="Inha Portal Password")
    args = parser.parse_args()

    # Instantiate an InhaCloud object
    inha = InhaCloud()

    # Try to login
    # If username and password are provided in arguments, they will override .env
    try:
        if inha.login(username=args.username, password=args.password):
            print("Login successful!")
            # Fetch login information and print name and student ID
            login_info = inha.fetch_login_info()
            if login_info:
                print(f"Name: {login_info['name']}")
                print(f"Student ID: {login_info['student_id']}")
            else:
                print("Could not fetch login information.")
        else:
            print("Login failed.")
            sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
