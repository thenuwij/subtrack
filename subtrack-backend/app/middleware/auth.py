import logging
import time
from datetime import datetime, timezone
from threading import Lock
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.algorithms import ECAlgorithm

from app.config import settings

logger = logging.getLogger(__name__)
security = HTTPBearer()

# Supabase migrated user access tokens from HS256 (legacy shared secret) to
# ES256 (asymmetric ECC P-256). ES256 keys resolve through the project's JWKS;
# the explicitly allow-listed HS256 path remains for legacy/local tokens while
# the application completes that rollover.
_JWKS_TTL_SECONDS = 3600
_JWKS_STALE_IF_ERROR_SECONDS = 86400
_JWKS_REFRESH_COOLDOWN_SECONDS = 60
_UNKNOWN_KID_TTL_SECONDS = 60
_MAX_NEGATIVE_KIDS = 256
_jwks_lock = Lock()
_jwks_cache: dict[str, Any] = {
    "url": None,
    "keys": None,
    "fetched_at": None,
    "last_attempt_at": None,
    "negative_kids": {},
}


def _now() -> float:
    # A monotonic clock is immune to NTP and daylight-saving jumps.
    return time.monotonic()


def _clear_jwks_cache_locked(url: str | None = None) -> None:
    _jwks_cache.update(
        {
            "url": url,
            "keys": None,
            "fetched_at": None,
            "last_attempt_at": None,
            "negative_kids": {},
        }
    )


def _reset_jwks_cache_for_tests() -> None:
    """Reset process-local state; intentionally private to the auth module."""
    with _jwks_lock:
        _clear_jwks_cache_locked()


def _cache_age(now: float) -> float | None:
    fetched_at = _jwks_cache["fetched_at"]
    if fetched_at is None:
        return None
    return max(0.0, now - fetched_at)


def _cached_keys_if_fresh(now: float) -> dict | None:
    age = _cache_age(now)
    if _jwks_cache["keys"] is not None and age is not None and age < _JWKS_TTL_SECONDS:
        return _jwks_cache["keys"]
    return None


def _cached_keys_if_usable(now: float) -> dict | None:
    age = _cache_age(now)
    if (
        _jwks_cache["keys"] is not None
        and age is not None
        and age < _JWKS_STALE_IF_ERROR_SECONDS
    ):
        return _jwks_cache["keys"]
    return None


def _refresh_is_on_cooldown(now: float) -> bool:
    last_attempt_at = _jwks_cache["last_attempt_at"]
    return (
        last_attempt_at is not None
        and max(0.0, now - last_attempt_at) < _JWKS_REFRESH_COOLDOWN_SECONDS
    )


def _fetch_jwks(force: bool = False) -> dict | None:
    if not settings.supabase_url:
        return None
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    # Keep keys scoped to the configured issuer. This mainly matters for test
    # isolation, but also makes a runtime configuration change fail closed.
    with _jwks_lock:
        if _jwks_cache["url"] != url:
            _clear_jwks_cache_locked(url)

    now = _now()
    if not force:
        fresh = _cached_keys_if_fresh(now)
        if fresh is not None:
            return fresh
    if _refresh_is_on_cooldown(now):
        return _cached_keys_if_usable(now)

    # The lock makes refreshes single-flight. Waiting requests re-check the
    # cache and cooldown after the active request finishes, so one upstream
    # outage or key rotation cannot create a per-request JWKS stampede.
    with _jwks_lock:
        now = _now()
        if not force:
            fresh = _cached_keys_if_fresh(now)
            if fresh is not None:
                return fresh
        if _refresh_is_on_cooldown(now):
            return _cached_keys_if_usable(now)

        _jwks_cache["last_attempt_at"] = now
        try:
            resp = httpx.get(url, timeout=5.0)
            resp.raise_for_status()
            document = resp.json()
            if not isinstance(document, dict) or not isinstance(
                document.get("keys"), list
            ):
                raise TypeError("JWKS response did not contain a keys array")
            if not all(isinstance(key, dict) for key in document["keys"]):
                raise TypeError("JWKS keys array contained an invalid entry")
            _jwks_cache["keys"] = document
            _jwks_cache["fetched_at"] = now
            _jwks_cache["negative_kids"] = {}
            return document
        except Exception as exc:  # noqa: BLE001 - stale-on-error is the trust boundary
            stale = _cached_keys_if_usable(now)
            logger.warning(
                "Failed to refresh Supabase JWKS from %s; %s cached keys: %s",
                url,
                "using" if stale is not None else "no usable",
                exc,
            )
            return stale


def _search(jwks: dict | None, kid: str) -> dict | None:
    for key in (jwks or {}).get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


def _find_jwk(kid: str) -> dict | None:
    # Cache first; only force a refetch when the kid is unknown (key rotation).
    # Building both results eagerly here used to fire the forced HTTP fetch on
    # every single request, adding a Supabase round-trip to every API call.
    found = _search(_fetch_jwks(), kid)
    if found is not None:
        return found

    now = _now()
    with _jwks_lock:
        negative_kids: dict[str, float] = _jwks_cache["negative_kids"]
        for cached_kid, expires_at in list(negative_kids.items()):
            if expires_at <= now:
                negative_kids.pop(cached_kid, None)
        if negative_kids.get(kid, 0.0) > now:
            return None

    found = _search(_fetch_jwks(force=True), kid)
    if found is not None:
        return found

    with _jwks_lock:
        negative_kids = _jwks_cache["negative_kids"]
        if len(negative_kids) >= _MAX_NEGATIVE_KIDS:
            negative_kids.pop(next(iter(negative_kids)))
        negative_kids[kid] = _now() + _UNKNOWN_KID_TTL_SECONDS
    return None


DEMO_TOKEN_ALGORITHM = "HS512"
DEMO_TOKEN_AUDIENCE = "subtrack-demo"
DEMO_USER_PREFIX = "demo_"


def is_demo_user(user_id: str) -> bool:
    return user_id.startswith(DEMO_USER_PREFIX)


def reject_demo_user(user_id: str, action: str) -> None:
    if is_demo_user(user_id):
        raise HTTPException(
            status_code=403,
            detail=f"{action} isn't available in the demo. Create a free account to use it.",
        )


def issue_demo_token(user_id: str, expires_at: datetime) -> str:
    if not settings.demo_token_secret or not is_demo_user(user_id):
        raise ValueError("Demo tokens are not available")
    return jwt.encode(
        {
            "sub": user_id,
            "aud": DEMO_TOKEN_AUDIENCE,
            "iss": DEMO_TOKEN_AUDIENCE,
            "exp": int(expires_at.replace(tzinfo=timezone.utc).timestamp()),
        },
        settings.demo_token_secret,
        algorithm=DEMO_TOKEN_ALGORITHM,
    )


def verify_demo_token(token: str) -> str:
    if not settings.demo_token_secret:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    payload = jwt.decode(
        token,
        settings.demo_token_secret,
        algorithms=[DEMO_TOKEN_ALGORITHM],
        audience=DEMO_TOKEN_AUDIENCE,
        issuer=DEMO_TOKEN_AUDIENCE,
        leeway=30,
        options={"require": ["exp", "sub", "aud", "iss"]},
    )
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not is_demo_user(user_id) or len(user_id) > 64:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user_id


def verify_token(
    credentials: HTTPAuthorizationCredentials = Security(security),  # noqa: B008
) -> str:
    token = credentials.credentials
    try:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        kid = header.get("kid")

        if algorithm == "ES256":
            if not isinstance(kid, str) or not kid or len(kid) > 256:
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            jwk_dict = _find_jwk(kid)
            if jwk_dict is None:
                logger.warning("No matching JWK found for access token")
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            try:
                key = ECAlgorithm.from_jwk(jwk_dict)
            except Exception as e:  # noqa: BLE001 - malformed public key becomes 401
                logger.error("Failed to construct EC key from matched JWK: %s", e)
                raise HTTPException(status_code=401, detail="Invalid or expired token") from None
            algorithms = ["ES256"]
        elif algorithm == DEMO_TOKEN_ALGORITHM:
            return verify_demo_token(token)
        elif algorithm == "HS256":
            # Some legacy Supabase HS256 tokens include a kid. The verified
            # algorithm, rather than kid presence, decides the compatibility
            # path so those tokens continue to work without algorithm mixing.
            key = settings.supabase_jwt_secret
            algorithms = ["HS256"]
        else:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        decode_options: dict[str, Any] = {
            "algorithms": algorithms,
            "audience": "authenticated",
            "leeway": 30,
            "options": {"require": ["exp", "sub", "aud"]},
        }
        if settings.supabase_url:
            decode_options["issuer"] = f"{settings.supabase_url.rstrip('/')}/auth/v1"
            decode_options["options"]["require"].append("iss")
        payload = jwt.decode(token, key, **decode_options)
        user_id = payload.get("sub")
        if not isinstance(user_id, str) or not user_id or len(user_id) > 255:
            logger.error("JWT payload contained an invalid subject claim")
            raise HTTPException(status_code=401, detail="Invalid token")
        return user_id
    except HTTPException:
        raise
    except jwt.PyJWTError as e:
        logger.error("JWT verification failed: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None
    except Exception as e:  # noqa: BLE001 - never leak verifier internals to clients
        logger.error("Unexpected error during token verification: %s", e)
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None
