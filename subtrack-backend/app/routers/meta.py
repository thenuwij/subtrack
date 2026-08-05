import os

from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/meta", tags=["meta"])

# These flags let independently deployed frontends fail closed when a backend
# is behind, rather than rendering controls whose contract is not available.
CAPABILITIES = {
    "flexible_cadence_v1": True,
    "lifecycle_v1": True,
    "exact_forecast_v1": True,
    "variable_amounts_v1": True,
    "server_equivalents_v1": True,
    "gmail_secure_oauth_v1": True,
    "data_export_v1": True,
    "app_data_deletion_v1": True,
}


def release_metadata() -> dict[str, str]:
    return {
        "environment": settings.environment,
        "commit": os.getenv("RENDER_GIT_COMMIT")
        or os.getenv("SUBTRACK_RELEASE")
        or "unknown",
        "service": os.getenv("RENDER_SERVICE_NAME", "subtrack-api"),
    }


@router.get("/capabilities")
def get_capabilities() -> dict:
    from app.routers.gmail import gmail_is_configured

    return {
        "api": {"name": "Subtrack API", "version": "1"},
        "release": release_metadata(),
        "capabilities": {
            **CAPABILITIES,
            "gmail_configured": gmail_is_configured(),
        },
    }
