"""Safe, best-effort revocation of stored Google refresh tokens.

Deleting Subtrack's encrypted copy is the privacy-critical operation: once it
is gone, this service can no longer access the mailbox.  Revoking the token at
Google is an additional defence.  Google is an external dependency, so a
temporary outage must never prevent local data deletion.
"""

from __future__ import annotations

import logging
from enum import Enum

import httpx

from app.gmail.crypto import TokenUndecryptable, decrypt_token

logger = logging.getLogger(__name__)

GOOGLE_REVOCATION_URL = "https://oauth2.googleapis.com/revoke"


class GmailRevocationStatus(str, Enum):
    revoked = "revoked"
    failed = "failed"
    not_connected = "not_connected"


def revoke_encrypted_refresh_token(
    encrypted_token: str | None,
) -> GmailRevocationStatus:
    """Revoke a stored Google token without logging or returning the secret.

    The caller must still delete its local token when this returns ``failed``.
    That status lets the UI recommend removing Subtrack from the user's Google
    permissions, while preserving the user's right to delete local data even
    if Google is unavailable.
    """

    if not encrypted_token:
        return GmailRevocationStatus.not_connected

    try:
        refresh_token = decrypt_token(encrypted_token)
    except (TokenUndecryptable, RuntimeError):
        logger.warning(
            "Could not decrypt a Gmail token for revocation; local deletion will continue"
        )
        return GmailRevocationStatus.failed

    try:
        response = httpx.post(
            GOOGLE_REVOCATION_URL,
            data={"token": refresh_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=httpx.Timeout(5.0, connect=2.0),
        )
    except httpx.HTTPError:
        logger.warning(
            "Google token revocation was unavailable; local deletion will continue"
        )
        return GmailRevocationStatus.failed
    finally:
        # Avoid retaining a second long-lived reference after the request.
        refresh_token = ""

    if response.status_code == 200:
        return GmailRevocationStatus.revoked

    logger.warning(
        "Google token revocation returned status %d; local deletion will continue",
        response.status_code,
    )
    return GmailRevocationStatus.failed
