import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.database import Base, engine
from app.routers import subscriptions, rates, preferences, savings, agent, gmail, detected


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
app.include_router(savings.router)
app.include_router(agent.router)
app.include_router(gmail.router)
app.include_router(detected.router)

@app.on_event("startup")
def on_startup():
    logger.info("Subtrack API started")

@app.get("/")
def health_check():
    return {"status": "ok", "app": "Subtrack API"}