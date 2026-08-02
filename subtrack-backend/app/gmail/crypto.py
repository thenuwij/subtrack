"""Encryption for stored OAuth refresh tokens.

A refresh token is long-lived access to someone's mailbox. Storing it in
plaintext means a database dump is a mailbox dump, so it never touches the
DB unencrypted.
"""
from cryptography.fernet import Fernet
from app.config import settings


def _cipher() -> Fernet:
    if not settings.token_encryption_key:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is not set. Generate one with:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return Fernet(settings.token_encryption_key.encode())


def encrypt_token(token: str) -> str:
    return _cipher().encrypt(token.encode()).decode()


def decrypt_token(token_encrypted: str) -> str:
    return _cipher().decrypt(token_encrypted.encode()).decode()
