import logging
import time
from typing import Any, Optional

import httpx
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

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
        logger.warning("Failed to fetch Supabase JWKS from %s: %s", url, e)
        return None


def _find_jwk(kid: str) -> Optional[dict]:
    for jwks in (_fetch_jwks(), _fetch_jwks(force=True)):
        if not jwks:
            continue
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
    return None


def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)) -> str:
    token = credentials.credentials
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "HS256")
        kid = header.get("kid")

        if alg != "HS256" and kid:
            jwk_dict = _find_jwk(kid)
            if jwk_dict is None:
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            from jose import jwk as jose_jwk
            key: Any = jose_jwk.construct(jwk_dict, algorithm=alg)
            algorithms = [alg]
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
            raise HTTPException(status_code=401, detail="Invalid token")
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
