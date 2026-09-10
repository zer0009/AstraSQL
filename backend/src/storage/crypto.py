import base64
import hashlib

from cryptography.fernet import Fernet

from src.config.settings import get_settings


def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.encryption_key.encode("utf-8")
    # Fernet requires a 32-byte url-safe base64-encoded key
    try:
        return Fernet(key)
    except (ValueError, Exception):
        derived = base64.urlsafe_b64encode(hashlib.sha256(key).digest())
        return Fernet(derived)


def encrypt_password(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_password(token: str) -> str:
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
