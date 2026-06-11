"""Column-level encryption for PII at rest.

Uses Fernet (symmetric AES-256-CBC) when ENCRYPTION_KEY is configured.
When encryption is disabled (empty key), values pass through unmodified.
This is opt-in -- set ENCRYPTION_KEY in .env to enable.

Sensitive columns encrypted:
- users.email (deterministic, so UNIQUE constraint + login lookups work)
- Future: citizens.pseudonyme, reports.texte, participants.pseudonyme
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from cryptography.fernet import Fernet
from app.config import get_settings

logger = logging.getLogger("encryption")

_fernet: Fernet | None = None


def _get_fernet() -> Fernet | None:
    global _fernet
    if _fernet is not None:
        return _fernet
    s = get_settings()
    if not s.encryption_key:
        return None
    key_bytes = hashlib.sha256(s.encryption_key.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes[:32])
    _fernet = Fernet(fernet_key)
    return _fernet


def _hmac_prefix(value: str) -> str:
    """Deterministic 32-char hex prefix from HMAC-SHA256(key, value)."""
    s = get_settings()
    key_bytes = hashlib.sha256(s.encryption_key.encode()).digest()
    return hmac.new(key_bytes, value.encode(), hashlib.sha256).hexdigest()[:32]


def encrypt(value: str | None) -> str | None:
    """Non-deterministic encryption for content blobs (reports, messages)."""
    if value is None:
        return None
    f = _get_fernet()
    if f is None:
        return value
    try:
        return "ENC:" + f.encrypt(value.encode()).decode()
    except Exception:
        logger.warning("encryption_failed", exc_info=True)
        return value


def decrypt(value: str | None) -> str | None:
    """Decrypt a value prefixed with 'ENC:'. Returns original otherwise."""
    if value is None:
        return None
    if not value.startswith("ENC:"):
        return value
    f = _get_fernet()
    if f is None:
        return value[4:]
    try:
        return f.decrypt(value[4:].encode()).decode()
    except Exception:
        logger.warning("decryption_failed", exc_info=True)
        return value


def encrypt_deterministic(value: str) -> str:
    """Deterministic encryption -- same input always produces same output.

    Format: ENC:<hmac_prefix>:<fernet_ciphertext>
    The HMAC prefix enables UNIQUE constraints and lookup queries.
    """
    f = _get_fernet()
    if f is None:
        return value
    prefix = _hmac_prefix(value)
    ciphertext = f.encrypt(value.encode()).decode()
    return f"ENC:{prefix}:{ciphertext}"


def decrypt_deterministic(value: str | None) -> str | None:
    """Decrypt a deterministically-encrypted value."""
    if value is None:
        return None
    if not value.startswith("ENC:"):
        return value
    f = _get_fernet()
    if f is None:
        return value
    parts = value.split(":", 2)
    if len(parts) != 3 or not parts[2]:
        logger.warning("invalid_deterministic_format")
        return value
    try:
        return f.decrypt(parts[2].encode()).decode()
    except Exception:
        logger.warning("decryption_failed", exc_info=True)
        return value


def make_email_lookup(value: str) -> str:
    """Build a LIKE pattern for encrypted email lookup.

    Returns the original value if encryption is off, otherwise
    returns 'ENC:<prefix>:%' for use in WHERE email LIKE %s.
    """
    f = _get_fernet()
    if f is None:
        return value
    prefix = _hmac_prefix(value)
    return f"ENC:{prefix}:%"
