import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.routers import (
    account,
    agent,
    demo,
    detected,
    gmail,
    meta,
    preferences,
    rates,
    reminders,
    subscriptions,
)
from app.routers.meta import release_metadata

# Logging config
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
_ALLOWED_ORIGINS = tuple(
    origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    on_startup()
    try:
        yield
    finally:
        on_shutdown()


app = FastAPI(title="Subtrack API", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(subscriptions.router)
app.include_router(rates.router)
app.include_router(preferences.router)
app.include_router(account.router)
app.include_router(agent.router)
app.include_router(gmail.router)
app.include_router(detected.router)
app.include_router(reminders.router)
app.include_router(meta.router)
app.include_router(demo.router)


@app.middleware("http")
async def protect_api_responses(request: Request, call_next):
    request_id = str(uuid4())
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # Never log the query string: the Gmail callback contains a short-lived
        # authorization code and OAuth state in its URL parameters.
        logger.exception(
            "Unhandled API error for %s %s request_id=%s",
            request.method,
            request.url.path,
            request_id,
        )
        response = JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )
        _apply_error_cors(request, response)

    _apply_response_headers(response, request_id)
    if request.url.path != "/health/ready":
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.info(
            "%s %s %d %.1fms request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request_id,
        )
    return response


def _apply_response_headers(response: Response, request_id: str) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if settings.environment == "production":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    response.headers["X-Request-ID"] = request_id


def _apply_error_cors(request: Request, response: Response) -> None:
    """Keep browser-visible 500s diagnosable without opening CORS broadly."""
    origin = request.headers.get("origin")
    if origin not in _ALLOWED_ORIGINS:
        return
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Credentials"] = "true"
    vary = {
        item.strip()
        for item in response.headers.get("Vary", "").split(",")
        if item.strip()
    }
    vary.add("Origin")
    response.headers["Vary"] = ", ".join(sorted(vary))


def on_startup():
    # A bad encryption key makes every Gmail scan fail. Surface it at boot,
    # where a deploy can catch it, instead of at a user's first scan.
    if settings.google_client_id:
        from app.gmail.crypto import check_configured

        check_configured()

    # Only stale work is failed. Marking every running row at boot breaks as
    # soon as Render has more than one instance: a new instance would cancel
    # healthy work owned by another one.
    from app.database import SessionLocal
    from app.models import AgentAction, AgentMessage, GmailAccount
    from app.routers.gmail import (
        INTERRUPTED_MESSAGE,
        SCAN_TIME_LIMIT_SECONDS,
        STALE_SCAN_MINUTES,
    )

    db = SessionLocal()
    try:
        gmail_cutoff = _utcnow() - timedelta(minutes=STALE_SCAN_MINUTES)
        gmail_total_cutoff = _utcnow() - timedelta(
            seconds=SCAN_TIME_LIMIT_SECONDS + 15,
        )
        interrupted = (
            db.query(GmailAccount)
            .filter(
                GmailAccount.scan_status == "running",
                (
                    (GmailAccount.scan_heartbeat_at < gmail_cutoff)
                    | (GmailAccount.scan_started_at < gmail_total_cutoff)
                    | (
                        GmailAccount.scan_heartbeat_at.is_(None)
                        & (GmailAccount.scan_started_at < gmail_cutoff)
                    )
                    | (
                        GmailAccount.scan_heartbeat_at.is_(None)
                        & GmailAccount.scan_started_at.is_(None)
                    )
                ),
            )
            .update(
                {
                    "scan_status": "error",
                    "scan_error": INTERRUPTED_MESSAGE,
                    "scan_stage": None,
                },
                synchronize_session=False,
            )
        )
        if interrupted:
            db.commit()
            logger.warning(
                "Marked %d interrupted scan(s) as failed at startup", interrupted
            )

        agent_cutoff = _utcnow() - timedelta(minutes=10)
        interrupted_message_ids = [
            row[0]
            for row in db.query(AgentMessage.id)
            .filter(
                AgentMessage.status == "streaming",
                AgentMessage.updated_at < agent_cutoff,
            )
            .all()
        ]
        if interrupted_message_ids:
            db.query(AgentAction).filter(
                AgentAction.assistant_message_id.in_(interrupted_message_ids),
                AgentAction.status == "pending",
            ).update(
                {
                    "status": "failed",
                    "error_code": "response_failed",
                    "error_message": "The assistant response was interrupted. Ask again to recreate this action.",
                },
                synchronize_session=False,
            )

        interrupted_replies = (
            db.query(AgentMessage)
            .filter(
                AgentMessage.status == "streaming",
                AgentMessage.updated_at < agent_cutoff,
            )
            .update(
                {
                    "status": "failed",
                    "error_code": "stream_interrupted",
                }
            )
        )
        if interrupted_replies:
            db.commit()
            logger.warning(
                "Marked %d interrupted agent response(s) as failed at startup",
                interrupted_replies,
            )
    finally:
        db.close()

    logger.info("Subtrack API started")


def on_shutdown():
    from app.routers.gmail import shutdown_scan_executor

    shutdown_scan_executor()


@app.get("/")
def health_check():
    return {"status": "ok", "app": "Subtrack API", "release": release_metadata()}


@lru_cache(maxsize=1)
def _expected_schema_revision() -> str | None:
    """The migration this build of the code expects, read once from disk."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        root = Path(__file__).resolve().parents[1]
        heads = ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_heads()
        return heads[0] if len(heads) == 1 else None
    except Exception:  # noqa: BLE001 - a readiness probe must not crash on this
        logger.warning("Could not determine the expected schema revision")
        return None


def _schema_revision(connection) -> str | None:
    """The migration actually applied to this database, or None if unknowable."""
    try:
        return connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
    except Exception:  # noqa: BLE001 - absent table means an unmigrated database
        return None


@app.get("/health/ready")
def readiness_check():
    """Ready means the database is reachable *and* matches this code.

    A reachable database is not a working one. Shipping code whose migrations
    have not been applied left every signed-in page returning 500 while the
    deploy looked perfectly healthy — the queries referenced columns that did
    not exist yet. Checking the revision here turns that into a failed deploy
    that keeps the previous version serving, which matters most where the
    migration cannot run automatically before release.
    """
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        expected = _expected_schema_revision()
        applied = _schema_revision(connection)

    # Only a definite mismatch fails. An unreadable revision on either side is
    # reported rather than guessed at, so a probe never blocks a release over
    # something it could not actually determine.
    if expected is not None and applied is not None and applied != expected:
        logger.error(
            "Database schema is at %s but this build expects %s", applied, expected,
        )
        raise HTTPException(
            status_code=503,
            detail=(
                f"Database schema is at {applied}; this release expects {expected}. "
                "Run `python scripts/migrate.py` against it, then redeploy."
            ),
        )

    return {
        "status": "ready",
        "app": "Subtrack API",
        "release": release_metadata(),
        "schema_revision": applied,
    }
