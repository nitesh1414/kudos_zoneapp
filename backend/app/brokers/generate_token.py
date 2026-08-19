"""
app/brokers/generate_token.py — Token utility for Fyers OAuth flow.
"""

import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from dotenv import load_dotenv
from fyers_apiv3 import fyersModel

env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

CLIENT_ID = os.getenv("FYERS_CLIENT_ID", "937RN4D2JZ-100")
SECRET_KEY = os.getenv("FYERS_SECRET_KEY", "5BZ4LOWW38")
REDIRECT_URI = "https://trade.fyers.in/api-login/redirect-uri/index.html"


def get_login_url() -> str:
    session = fyersModel.SessionModel(
        client_id=CLIENT_ID,
        secret_key=SECRET_KEY,
        redirect_uri=REDIRECT_URI,
        response_type="code",
        grant_type="authorization_code",
    )
    return session.generate_authcode()


def exchange_code_for_token(auth_code_or_url: str) -> str:
    if "auth_code=" in auth_code_or_url:
        parsed = urlparse(auth_code_or_url)
        auth_code = parse_qs(parsed.query).get("auth_code", [""])[0]
    else:
        auth_code = auth_code_or_url.strip()

    if not auth_code:
        raise ValueError("Invalid auth_code provided.")

    session = fyersModel.SessionModel(
        client_id=CLIENT_ID,
        secret_key=SECRET_KEY,
        redirect_uri=REDIRECT_URI,
        response_type="code",
        grant_type="authorization_code",
    )
    session.set_token(auth_code)
    response = session.generate_token()
    token = response.get("access_token")
    if not token:
        raise RuntimeError(f"Token generation failed: {response}")

    # Save to .fyers_token
    token_path = Path(__file__).resolve().parent.parent.parent / ".fyers_token"
    token_path.write_text(token)
    os.environ["FYERS_ACCESS_TOKEN"] = token
    return token


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("FYERS LOGIN URL:")
    print(get_login_url())
    print("=" * 70)
    user_input = input("\nPaste redirected URL or auth_code here: ").strip()
    if user_input:
        tok = exchange_code_for_token(user_input)
        print(f"\n[SUCCESS] Token active and saved! ({tok[:15]}...)")