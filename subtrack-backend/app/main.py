import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.config import settings
from app.database import engine
from app.routers import subscriptions, rates, preferences, agent, gmail, detected, reminders


# Logging config
logging.basicConfig(
    level = logging.INFO,
    format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt= "%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

app = FastAPI(title="Subtrack API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(subscriptions.router)
app.include_router(rates.router)
app.include_router(preferences.router)
app.include_router(agent.router)
app.include_router(gmail.router)
app.include_router(detected.router)
app.include_router(reminders.router)


@app.middleware("http")
async def protect_api_responses(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Request-ID"] = str(uuid4())
    return response

@app.on_event("startup")
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
    from app.routers.gmail import INTERRUPTED_MESSAGE, STALE_SCAN_MINUTES
    db = SessionLocal()
    try:
        gmail_cutoff = _utcnow() - timedelta(minutes=STALE_SCAN_MINUTES)
        interrupted = (
            db.query(GmailAccount)
            .filter(
                GmailAccount.scan_status == "running",
                (
                    (GmailAccount.scan_heartbeat_at < gmail_cutoff)
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
            .update({
                "scan_status": "error",
                "scan_error": INTERRUPTED_MESSAGE,
                "scan_stage": None,
            }, synchronize_session=False)
        )
        if interrupted:
            db.commit()
            logger.warning("Marked %d interrupted scan(s) as failed at startup", interrupted)

        agent_cutoff = _utcnow() - timedelta(minutes=10)
        interrupted_message_ids = [
            row[0] for row in db.query(AgentMessage.id).filter(
                AgentMessage.status == "streaming",
                AgentMessage.updated_at < agent_cutoff,
            ).all()
        ]
        if interrupted_message_ids:
            db.query(AgentAction).filter(
                AgentAction.assistant_message_id.in_(interrupted_message_ids),
                AgentAction.status == "pending",
            ).update({
                "status": "failed",
                "error_code": "response_failed",
                "error_message": "The assistant response was interrupted. Ask again to recreate this action.",
            }, synchronize_session=False)

        interrupted_replies = (
            db.query(AgentMessage)
            .filter(
                AgentMessage.status == "streaming",
                AgentMessage.updated_at < agent_cutoff,
            )
            .update({
                "status": "failed",
                "error_code": "stream_interrupted",
            })
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


@app.on_event("shutdown")
def on_shutdown():
    from app.routers.gmail import shutdown_scan_executor
    shutdown_scan_executor()

@app.get("/")
def health_check():
    return {"status": "ok", "app": "Subtrack API"}


@app.get("/health/ready")
def readiness_check():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ready", "app": "Subtrack API"}
