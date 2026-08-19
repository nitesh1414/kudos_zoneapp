"""Optional CLI helper for completing a Fyers OAuth exchange.

It never stores the resulting token. Paste the token into an encrypted broker
connection in the administrator UI.
"""
import os
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from fyers_apiv3 import fyersModel

load_dotenv()


def _settings():
    values=(os.getenv("FYERS_CLIENT_ID"),os.getenv("FYERS_SECRET_KEY"),os.getenv("FYERS_REDIRECT_URI"))
    if not all(values): raise RuntimeError("Set FYERS_CLIENT_ID, FYERS_SECRET_KEY and FYERS_REDIRECT_URI")
    return values


def get_login_url():
    client,secret,redirect=_settings()
    return fyersModel.SessionModel(client_id=client,secret_key=secret,redirect_uri=redirect,response_type="code",grant_type="authorization_code").generate_authcode()


def exchange_code_for_token(auth_code_or_url):
    auth_code=parse_qs(urlparse(auth_code_or_url).query).get("auth_code",[""])[0] if "auth_code=" in auth_code_or_url else auth_code_or_url.strip()
    if not auth_code: raise ValueError("Invalid auth_code")
    client,secret,redirect=_settings()
    session=fyersModel.SessionModel(client_id=client,secret_key=secret,redirect_uri=redirect,response_type="code",grant_type="authorization_code")
    session.set_token(auth_code); response=session.generate_token(); token=response.get("access_token")
    if not token: raise RuntimeError(f"Token generation failed: {response}")
    return token


if __name__=="__main__":
    print("Open this URL:",get_login_url())
    token=exchange_code_for_token(input("Paste redirected URL or auth_code: ").strip())
    print("Paste this token into ZoneApp admin (it has not been written to disk):\n",token)
