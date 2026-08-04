"""Encryption for stored OAuth refresh tokens.

A refresh token is long-lived access to someone's mailbox. Storing it in
plaintext means a database dump is a mailbox dump, so it never touches the
DB unencrypted.
"""
from cryptography.fernet import Fernet, InvalidToken
from app.config import settings

GENERATE_HINT = (
    'python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())"'
)


class TokenUndecryptable(Exception):
    """The stored token cannot be read with the key this deployment holds.

    Almost always a key mismatch between environments sharing one database:
    the token was encrypted elsewhere. The token is not recoverable, so the
    only way forward is for the user to reconnect.
    """


def check_configured() -> None:
    """Fail at startup rather than at a user's first scan.

    A missing or malformed key isn't discoverable until something tries to
    decrypt, which in practice means a user clicking Scan and getting an error
    for a deployment that was broken the moment it went live.
    """
    key = settings.token_encryption_key
    if not key:
        raise RuntimeError(
            f"TOKEN_ENCRYPTION_KEY is not set. Generate one with:\n  {GENERATE_HINT}\n"
            "It must be identical everywhere that shares this database — a token "
            "encrypted with one key cannot be read with another."
        )
    try:
        Fernet(key.encode())
    except Exception as exc:
        raise RuntimeError(
            f"TOKEN_ENCRYPTION_KEY is not a valid Fernet key ({exc}). "
            f"Generate one with:\n  {GENERATE_HINT}"
        ) from exc


def _cipher() -> Fernet:
    check_configured()
    return Fernet(settings.token_encryption_key.encode())


def encrypt_token(token: str) -> str:
    return _cipher().encrypt(token.encode()).decode()


def decrypt_token(token_encrypted: str) -> str:
    try:
        return _cipher().decrypt(token_encrypted.encode()).decode()
    except InvalidToken as exc:
        raise TokenUndecryptable(
            "This mailbox was connected under a different encryption key, so its "
            "saved access can no longer be read."
        ) from exc
