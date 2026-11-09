"""Encrypt store access tokens at rest."""

from cryptography.fernet import Fernet

from shopchat.config import get_settings


def _fernet() -> Fernet:
    key = get_settings().token_encryption_key
    if key is None:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not set")
    return Fernet(key.get_secret_value().encode())


def encrypt_token(token: str) -> bytes:
    return _fernet().encrypt(token.encode())


def decrypt_token(data: bytes) -> str:
    return _fernet().decrypt(data).decode()
