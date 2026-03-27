from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.database import Base, engine
from app.routers import subscriptions, expenses, budgets

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
app.include_router(expenses.router)
app.include_router(budgets.router)

@app.get("/")
def health_check():
    return {"status": "ok", "app": "Subtrack API"}