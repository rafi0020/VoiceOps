"""Password hashing with scrypt (memory-hard, standard library)."""

import base64
import hashlib
import hmac
import os
import re

from app.config import get_settings

MIN_LENGTH = 10


def password_problem(password: str) -> str | None:
    """Why a new password is not acceptable, or None when it is."""
    if len(password) < MIN_LENGTH:
        return f"Password must be at least {MIN_LENGTH} characters."
    if len(password) > 200:
        return "Password must be at most 200 characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password must contain a letter and a number."
    return None


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=2**27)


def hash_password(password: str) -> str:
    n, r, p = get_settings().scrypt_n, 8, 1
    salt = os.urandom(16)
    digest = _derive(password, salt, n, r, p)
    return f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = _derive(password, base64.b64decode(salt), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


_dummy: str | None = None


def dummy_hash() -> str:
    """A real hash to verify against when the account does not exist, so timing does not reveal that."""
    global _dummy
    if _dummy is None:
        _dummy = hash_password(base64.b64encode(os.urandom(18)).decode())
    return _dummy
