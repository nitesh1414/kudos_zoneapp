"""Password, session and broker-secret helpers (stdlib PBKDF2 + Fernet)."""
import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken

COOKIE_NAME = "zoneapp_session"
SESSION_DAYS = 7


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return "pbkdf2_sha256$310000$%s$%s" % (
        base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(digest).decode())


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, rounds, salt, expected = encoded.split("$", 3)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.urlsafe_b64decode(salt), int(rounds))
        return hmac.compare_digest(actual, base64.urlsafe_b64decode(expected))
    except (ValueError, TypeError):
        return False


def create_session(store, user_id: int):
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    store.exec("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES (?,?,?)", [token_hash,user_id,expires])
    return token, expires


def session_user(store, token: str | None):
    if not token: return None
    digest = hashlib.sha256(token.encode()).hexdigest()
    return store.one("""SELECT u.id,u.username,u.display_name,u.role,u.symbol,u.active
        FROM sessions s JOIN users u ON u.id=s.user_id
        WHERE s.token_hash=? AND s.expires_at>now() AND u.active=true""", [digest])


def delete_session(store, token: str | None):
    if token:
        store.exec("DELETE FROM sessions WHERE token_hash=?", [hashlib.sha256(token.encode()).hexdigest()])


def _fernet():
    key = os.getenv("ZONEAPP_ENCRYPTION_KEY")
    if not key:
        # Stable fallback for local development; production should set a distinct key.
        seed = os.getenv("ZONEAPP_API_KEY", "zoneapp-local-development-key")
        key = base64.urlsafe_b64encode(hashlib.sha256(seed.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt_credentials(data: dict) -> dict:
    return {"encrypted": _fernet().encrypt(json.dumps(data).encode()).decode()}


def decrypt_credentials(data: dict) -> dict:
    try:
        return json.loads(_fernet().decrypt(data["encrypted"].encode()).decode())
    except (KeyError, InvalidToken, ValueError, TypeError):
        raise ValueError("Broker credentials cannot be decrypted; check ZONEAPP_ENCRYPTION_KEY")
