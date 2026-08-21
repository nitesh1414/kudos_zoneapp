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


# Every process that touches the database (API, worker, CLI scripts) must derive
# the same key, otherwise stored broker credentials become unreadable. Order:
#   1. ZONEAPP_ENCRYPTION_KEY  — what production should set
#   2. a random key persisted in the database, created on first use
#   3. legacy key derived from ZONEAPP_API_KEY (read-only, for old installations)
_KEY_PROVIDERS = []


def use_key_provider(provider):
    """Register a callable returning a stored Fernet key.

    Providers accumulate rather than replace each other: a process that talks
    to more than one database (the migration tooling, tests) must still be able
    to read rows written by the first one. Encryption always uses the first key
    in the list, so nothing is re-encrypted behind the operator's back.
    """
    if provider not in _KEY_PROVIDERS:
        _KEY_PROVIDERS.append(provider)


def new_encryption_key() -> str:
    return Fernet.generate_key().decode()


def _legacy_key() -> str:
    seed = os.getenv("ZONEAPP_API_KEY", "zoneapp-local-development-key")
    return base64.urlsafe_b64encode(hashlib.sha256(seed.encode()).digest()).decode()


def _keys() -> list:
    keys = []
    env_key = os.getenv("ZONEAPP_ENCRYPTION_KEY")
    if env_key:
        keys.append(env_key.strip())
    for provider in _KEY_PROVIDERS:
        try:
            stored = provider()
        except Exception:
            stored = None
        if stored:
            keys.append(stored)
    keys.append(_legacy_key())
    out = []
    for key in dict.fromkeys(keys):
        try:
            out.append(Fernet(key.encode()))
        except (ValueError, TypeError):
            continue
    if not out:
        raise ValueError("ZONEAPP_ENCRYPTION_KEY is not a valid Fernet key")
    return out


def _fernet():
    return _keys()[0]


def encrypt_credentials(data: dict) -> dict:
    return {"encrypted": _fernet().encrypt(json.dumps(data).encode()).decode()}


def decrypt_credentials(data: dict) -> dict:
    try:
        token = data["encrypted"].encode()
    except (KeyError, TypeError, AttributeError):
        raise ValueError("Stored broker credentials are malformed")
    for fernet in _keys():
        try:
            return json.loads(fernet.decrypt(token).decode())
        except (InvalidToken, ValueError, TypeError):
            continue
    raise ValueError(
        "Broker credentials cannot be decrypted with the current key. "
        "Restore ZONEAPP_ENCRYPTION_KEY, or re-enter the broker credentials.")
