import logging
import time
from typing import Any, Optional

import httpx
import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt.algorithms import ECAlgorithm

from app.config import settings

logger = logging.getLogger(__name__)
security = HTTPBearer()

# Supabase migrated user access tokens from HS256 (legacy shared secret) to
# ES256 (asymmetric ECC P-256). We resolve the signing key via the project's
# JWKS endpoint and only fall back to the HS256 secret when no matching key
# is found, so legacy/local tokens keep working during the rollover.
_JWKS_TTL_SECONDS = 3600
_jwks_cache: dict[str, Any] = {"keys": None, "fetched_at": 0.0}


def _fetch_jwks(force: bool = False) -> Optional[dict]:
    if not settings.supabase_url:
        return None
    now = time.time()
    if (
        not force
        and _jwks_cache["keys"] is not None
        and now - _jwks_cache["fetched_at"] < _JWKS_TTL_SECONDS
    ):
        return _jwks_cache["keys"]
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    try:
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
        _jwks_cache["keys"] = resp.json()
        _jwks_cache["fetched_at"] = now
        return _jwks_cache["keys"]
    except Exception as e:
        logger.error("Failed to fetch Supabase JWKS from %s: %s", url, e)
        return None


def _search(jwks: Optional[dict], kid: str) -> Optional[dict]:
    for key in (jwks or {}).get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


def _find_jwk(kid: str) -> Optional[dict]:
    # Cache first; only force a refetch when the kid is unknown (key rotation).
    # Building both results eagerly here used to fire the forced HTTP fetch on
    # every single request, adding a Supabase round-trip to every API call.
    found = _search(_fetch_jwks(), kid)
    if found is not None:
        return found
    return _search(_fetch_jwks(force=True), kid)


def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    token = credentials.credentials
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        if kid:
            jwk_dict = _find_jwk(kid)
            if jwk_dict is None:
                logger.error("No JWK found for kid=%s", kid)
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            try:
                key = ECAlgorithm.from_jwk(jwk_dict)
            except Exception as e:
                logger.error("Failed to construct EC key from JWK (kid=%s): %s", kid, e)
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            algorithms = ["ES256"]
        else:
            key = settings.supabase_jwt_secret
            algorithms = ["HS256"]

        payload = jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience="authenticated",
        )
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            logger.error("JWT payload missing 'sub' claim")
            raise HTTPException(status_code=401, detail="Invalid token")
        return user_id
    except HTTPException:
        raise
    except jwt.PyJWTError as e:
        logger.error("JWT verification failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except Exception as e:
        logger.error("Unexpected error during token verification: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token")
