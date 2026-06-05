import hashlib
import hmac
import os


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    real_salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        real_salt.encode("utf-8"),
        120000,
    ).hex()
    return digest, real_salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    digest, _ = hash_password(password=password, salt=salt)
    return hmac.compare_digest(digest, password_hash)
