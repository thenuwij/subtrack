import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.middleware.auth import DEMO_USER_PREFIX, issue_demo_token
from app.models import DemoSession
from app.services.demo import purge_expired_demos, seed_demo_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _client_address(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    if hops:
        return hops[-1]
    return request.client.host if request.client else "unknown"


def _client_hash(request: Request) -> str:
    return hmac.new(
        settings.demo_token_secret.encode(),
        _client_address(request).encode(),
        hashlib.sha256,
    ).hexdigest()


@router.post("/session", status_code=201)
def create_demo_session(request: Request, db: Session = Depends(get_db)):
    if not settings.demo_token_secret:
        raise HTTPException(status_code=404, detail="The demo is not available right now.")

    purge_expired_demos(db)
    now = _utcnow()
    hour_ago = now - timedelta(hours=1)
    client_hash = _client_hash(request)
    recent = db.query(DemoSession).filter(DemoSession.created_at >= hour_ago)
    if recent.filter(DemoSession.client_hash == client_hash).count() >= (
        settings.demo_sessions_per_client_per_hour
    ):
        raise HTTPException(
            status_code=429,
            detail="You have started several demos recently. Please try again in an hour.",
        )
    if recent.count() >= settings.demo_sessions_per_hour:
        raise HTTPException(
            status_code=429,
            detail="The demo is busy right now. Please try again shortly.",
        )

    expires_at = now + timedelta(hours=settings.demo_session_hours)
    user_id = f"{DEMO_USER_PREFIX}{uuid4().hex}"
    db.add(DemoSession(
        demo_user_id=user_id,
        client_hash=client_hash,
        created_at=now,
        expires_at=expires_at,
    ))
    db.commit()
    seed_demo_user(db, user_id)
    logger.info("Demo session created")
    return {
        "access_token": issue_demo_token(user_id, expires_at),
        "expires_at": f"{expires_at.isoformat()}Z",
    }
