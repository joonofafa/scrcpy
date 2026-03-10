"""TOTP authentication for external access."""

import hashlib
import logging
import os
import secrets
import time

import pyotp

from scrcpy_ai.config import config

logger = logging.getLogger(__name__)

# Session store: {token: expiry_timestamp}
_sessions: dict[str, float] = {}

SESSION_TTL = 15 * 60  # 15 minutes


def _secret_path() -> str:
    return os.path.join(config.db_dir, "totp_secret.key")


def get_or_create_secret() -> str:
    """Get existing TOTP secret or create a new one."""
    os.makedirs(config.db_dir, exist_ok=True)
    path = _secret_path()
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    secret = pyotp.random_base32()
    with open(path, "w") as f:
        f.write(secret)
    os.chmod(path, 0o600)
    logger.info("New TOTP secret generated: %s", path)
    return secret


def get_totp() -> pyotp.TOTP:
    return pyotp.TOTP(get_or_create_secret())


def get_provisioning_uri() -> str:
    """Get URI for QR code (Google Authenticator registration)."""
    totp = get_totp()
    return totp.provisioning_uri(name="scrcpy-ai", issuer_name="jhbot")


def verify_otp(code: str) -> bool:
    """Verify a TOTP code (allows 1 step tolerance for clock drift)."""
    totp = get_totp()
    return totp.verify(code, valid_window=1)


def create_session() -> str:
    """Create a new session token."""
    _cleanup_expired()
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_TTL
    return token


def validate_session(token: str) -> bool:
    """Check if session token is valid and refresh expiry."""
    if not token:
        return False
    expiry = _sessions.get(token)
    if not expiry:
        return False
    if time.time() > expiry:
        _sessions.pop(token, None)
        return False
    # Refresh TTL on activity
    _sessions[token] = time.time() + SESSION_TTL
    return True


def _cleanup_expired():
    """Remove expired sessions."""
    now = time.time()
    expired = [k for k, v in _sessions.items() if now > v]
    for k in expired:
        _sessions.pop(k, None)


def is_internal_request(client_host: str, forwarded_for: str | None) -> bool:
    """Check if request originates from localhost (not proxied external)."""
    # If X-Forwarded-For is set, it's coming through Apache proxy = external
    if forwarded_for:
        real_ip = forwarded_for.split(",")[0].strip()
        if real_ip not in ("127.0.0.1", "::1"):
            return False
    # Direct connection from localhost
    return client_host in ("127.0.0.1", "::1", "localhost")
