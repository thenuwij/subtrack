import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.database import Base, engine
from app.routers import subscriptions, rates, preferences, agent, gmail, detected


# Logging config
logging.basicConfig(
    level = logging.INFO,
    format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt= "%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Subtrack API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
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

@app.on_event("startup")
def on_startup():
    # A bad encryption key makes every Gmail scan fail. Surface it at boot,
    # where a deploy can catch it, instead of at a user's first scan.
    if settings.google_client_id:
        from app.gmail.crypto import check_configured
        check_configured()

    # Background scans don't survive a restart. Any scan marked "running" at
    # boot is dead — this process is the only one that runs them (single
    # instance, see render.yaml) — so mark it failed now rather than leaving
    # a spinner up until the staleness window expires. Partial results are
    # already committed batch-by-batch, so nothing found is lost.
    from app.database import SessionLocal
    from app.models import GmailAccount
    from app.routers.gmail import INTERRUPTED_MESSAGE
    db = SessionLocal()
    try:
        interrupted = (
            db.query(GmailAccount)
            .filter(GmailAccount.scan_status == "running")
            .update({"scan_status": "error", "scan_error": INTERRUPTED_MESSAGE})
        )
        if interrupted:
            db.commit()
            logger.warning("Marked %d interrupted scan(s) as failed at startup", interrupted)
    finally:
        db.close()

    logger.info("Subtrack API started")

@app.get("/")
def health_check():
    return {"status": "ok", "app": "Subtrack API"}