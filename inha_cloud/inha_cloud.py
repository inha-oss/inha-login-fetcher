import os
from typing import Optional, Dict

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

class InhaCloud:
    """A simple fetcher for Inha University login and user information."""

    def __init__(self, username: Optional[str] = None, password: Optional[str] = None):
        """
        Initialize InhaCloud object.
        
        Args:
            username: Inha Portal ID. If not provided, it will be loaded from .env.
            password: Inha Portal Password. If not provided, it will be loaded from .env.
        """
        # Load .env file
        load_dotenv()

        # Set user ID and password from args or environment
        self.username = username or os.getenv("INHA_USERNAME")
        self.password = password or os.getenv("INHA_PASSWORD")

        # URLs
        self.base_url = 'https://cloud.inha.ac.kr'
        self.login_url = f'{self.base_url}/auth/login'

        # Create session
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        })

        # Login user information
        self.student_id: Optional[str] = None
        self.name: Optional[str] = None

    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """
        Login to Inha University Cloud.
        
        Args:
            username: Optional username to override the initial one.
            password: Optional password to override the initial one.
            
        Returns:
            True if login is successful, False otherwise.
            
        Raises:
            ValueError: If username or password is not provided.
        """
        # Update username and password if provided
        if username:
            self.username = username
        if password:
            self.password = password

        # Validate credentials
        if not (self.username and self.password):
            message = (
                "Username and password are not provided.\n"
                "Please set INHA_USERNAME and INHA_PASSWORD in your .env file,\n"
                "or pass them as arguments to login()."
            )
            raise ValueError(message)

        try:
            # 1. GET main page to fetch CSRF token
            response = self._session.get(self.base_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            csrf_token = soup.select_one('input[name="_csrf"]')
            
            if not csrf_token:
                print("Error: Could not find CSRF token on the login page.")
                return False

            # 2. Prepare login payload
            payload = {
                'userid': self.username,
                'password': self.password,
                'loginDomain': 'inha.ac.kr',
                '_csrf': csrf_token['value']
            }

            # 3. POST login request
            res = self._session.post(self.login_url, data=payload)
            res.raise_for_status()

            # 4. Verify login and fetch info
            info = self.fetch_login_info()
            if info:
                return True
            else:
                print("Login failed: Invalid credentials or session not established.")
                return False

        except Exception as e:
            print(f"Login failed with error: {e}")
            return False

    def fetch_login_info(self) -> Optional[Dict[str, str]]:
        """
        Fetch user information from the portal.
        
        Returns:
            A dictionary containing 'name' and 'student_id' if successful, None otherwise.
        """
        try:
            # Request portal page
            res = self._session.get(self.base_url)
            res.raise_for_status()

            # Create BeautifulSoup object
            soup = BeautifulSoup(res.content, 'html.parser')

            # Get login user information
            # Note: The structure might have changed. In the login page, loginHeader says 'Sign in'.
            # After login, it typically contains the user's name and ID.
            login_header = soup.select_one('.loginHeader')
            
            if not login_header or 'data-userid' not in login_header.attrs:
                return None

            self.name = login_header.get_text(strip=True).split()[0]
            self.student_id = login_header.get('data-userid')

            if self.name and self.student_id:
                return {'name': self.name, 'student_id': self.student_id}
            
            return None

        except Exception as e:
            print(f"Failed to fetch login info: {e}")
            return None
