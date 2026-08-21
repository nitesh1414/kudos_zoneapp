"""Fyers OAuth helpers.

The credentials come from the stored broker connection whenever possible, so
the token that is generated always belongs to the app id the connection uses.
Environment variables are only a fallback for the CLI.
"""
import base64
import json
import os
import time
from urllib.parse import parse_qs, urlparse

from fyers_apiv3 import fyersModel


def settings(credentials: dict | None = None):
    """(client_id, secret_key, redirect_uri) from a connection, else the env."""
    credentials = credentials or {}
    client = (credentials.get("client_id") or os.getenv("FYERS_CLIENT_ID") or "").strip()
    secret = (credentials.get("secret_key") or os.getenv("FYERS_SECRET_KEY") or "").strip()
    redirect = (credentials.get("redirect_uri") or os.getenv("FYERS_REDIRECT_URI") or "").strip()
    missing = [name for name, value in
               (("client_id", client), ("secret_key", secret), ("redirect_uri", redirect)) if not value]
    if missing:
        raise ValueError("Missing " + ", ".join(missing) +
                         ". Add them to the broker connection (Edit credentials) or the .env file.")
    return client, secret, redirect


def _session(credentials: dict | None = None):
    client, secret, redirect = settings(credentials)
    return fyersModel.SessionModel(client_id=client, secret_key=secret, redirect_uri=redirect,
                                   response_type="code", grant_type="authorization_code")


def get_login_url(credentials: dict | None = None) -> str:
    return _session(credentials).generate_authcode()


def read_auth_code(value: str) -> str:
    """Accept a bare auth_code or the whole redirect URL that Fyers sends back."""
    value = (value or "").strip().strip('"').strip("'")
    if "auth_code=" in value:
        query = urlparse(value).query or value.split("?", 1)[-1]
        value = parse_qs(query).get("auth_code", [""])[0]
    return value.strip()


def exchange_code_for_token(auth_code_or_url: str, credentials: dict | None = None) -> str:
    auth_code = read_auth_code(auth_code_or_url)
    if not auth_code:
        raise ValueError("No auth_code found. Paste the full redirect URL or just the auth_code value.")
    session = _session(credentials)
    session.set_token(auth_code)
    response = session.generate_token()
    token = (response or {}).get("access_token")
    if not token:
        message = (response or {}).get("message") or response
        raise RuntimeError(f"Fyers rejected the auth code: {message}")
    return token


def clean_access_token(value: str, client_id: str | None = None) -> str:
    """Normalise whatever the administrator pasted into a bare access token.

    Fyers shows the token in several shapes: on its own, prefixed with the app
    id (``APPID-100:eyJ...``), wrapped in quotes, or inside the JSON response.
    """
    token = (value or "").strip().strip('"').strip("'")
    if token.startswith("{"):
        import json
        try:
            token = (json.loads(token).get("access_token") or "").strip()
        except ValueError:
            pass
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if ":" in token:
        prefix, _, rest = token.partition(":")
        # "<client_id>:<token>" — keep only the token part
        if rest and (not client_id or prefix.strip() == str(client_id).strip() or "-" in prefix):
            token = rest.strip()
    return token


# --------------------------------------------------------------------------
# Fyers hands out two long JWTs: the auth code and the access token. Pasting
# the wrong one is the usual cause of "Could not authenticate the user", so we
# read the (unverified) payload and say exactly what is wrong before the API
# call is made.
# --------------------------------------------------------------------------
def decode_claims(token: str) -> dict:
    """Best-effort read of a JWT payload. Never raises; {} when unreadable."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload).decode())
    except Exception:
        return {}


def looks_like_auth_code(token: str) -> bool:
    """True when the JWT is an auth code rather than an access token."""
    claims = decode_claims(token)
    sub = str(claims.get("sub", "")).lower()
    if sub:
        return "auth" in sub and "access" not in sub
    return False


def describe_token(token: str, client_id: str | None = None) -> dict:
    """What the token says about itself, and whether it can possibly work.

    Only claims that really identify the app are used. A Fyers access token
    carries ``aud`` as a list of scopes (``d:1``, ``x:0``…), never the app id,
    so it must not be read as one — doing so rejected valid tokens.
    """
    claims = decode_claims(token)
    raw_app_id = claims.get("appId") or claims.get("app_id") or claims.get("client_id")
    app_id = str(raw_app_id).strip() if isinstance(raw_app_id, (str, int)) else ""
    expires = claims.get("exp")
    info = {
        "kind": str(claims.get("sub") or ("unknown" if not claims else "token")),
        "app_id": app_id,
        "app_type": str(claims.get("appType") or "").strip(),
        "user": claims.get("fy_id") or claims.get("display_name"),
        "expires_at": expires,
        "expired": bool(expires and float(expires) < time.time()),
        "readable": bool(claims),
    }

    # Deliberately conservative: only refuse locally when the token cannot
    # possibly work. Anything else is left for the provider to judge.
    problem = None
    if looks_like_auth_code(token):
        problem = ("This is an auth code, not an access token. Paste the redirect URL or the auth code on its own "
                   "and it will be exchanged for you.")
    elif info["expired"]:
        problem = "This token has already expired. Generate today's token."
    elif app_id and client_id and app_id.split("-")[0].upper() != str(client_id).split("-")[0].upper():
        problem = (f"This token was issued for app id '{app_id}', but the connection uses '{client_id}'. "
                   f"Generate the token from this connection, or correct its App / Client ID.")
    info["problem"] = problem
    return info


if __name__ == "__main__":
    print("Open this URL:", get_login_url())
    print("Access token:\n", exchange_code_for_token(input("Paste redirected URL or auth_code: ")))
