from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

MIN_PASSWORD_LENGTH = 12

_hasher = PasswordHasher()
# Constant-time dummy for unknown usernames (must match hasher parameters).
_DUMMY_HASH = _hasher.hash("astrasql-timing-dummy-not-a-real-password")


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(password_hash: str, plain: str) -> bool:
    try:
        return bool(_hasher.verify(password_hash, plain))
    except (VerifyMismatchError, ValueError):
        return False


def verify_dummy_password(plain: str) -> None:
    """Burn the same verify cost when the username does not exist."""
    verify_password(_DUMMY_HASH, plain)


def validate_new_password(plain: str, *, default_password: str, current_password: str | None = None) -> str | None:
    """Return an error message if the new password is not acceptable."""
    if len(plain) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if plain == default_password:
        return "Choose a password that is not the default bootstrap password."
    if current_password is not None and plain == current_password:
        return "New password must be different from the current password."
    return None
