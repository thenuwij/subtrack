from ipaddress import ip_address
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_PRODUCTION_DATABASE_SCHEMES = {"postgresql", "postgresql+psycopg2"}


def _validate_https_url(
    value: str,
    *,
    label: str,
    origin_only: bool,
) -> str:
    """Validate a browser-facing production URL without rewriting it."""
    if value != value.strip() or "\\" in value or any(ord(char) < 33 for char in value):
        raise ValueError(f"{label} contains whitespace or invalid URL characters")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{label} must be an absolute HTTPS URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{label} must not contain credentials")
    hostname = parsed.hostname.lower()
    try:
        loopback_ip = ip_address(hostname).is_loopback
    except ValueError:
        loopback_ip = False
    if hostname in _LOCAL_HOSTS or hostname.endswith(".localhost") or loopback_ip:
        raise ValueError(f"{label} must not point to a local host in production")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} contains an invalid port") from exc
    if parsed.fragment:
        raise ValueError(f"{label} must not contain a URL fragment")
    if origin_only and (parsed.path not in ("", "/") or parsed.query):
        raise ValueError(f"{label} must be an origin without a path or query")
    if origin_only and value.endswith("/"):
        raise ValueError(f"{label} must not end with a slash")
    return value


def _validate_production_database_url(value: str) -> None:
    """Reject local or malformed databases before a production process boots."""
    if value != value.strip() or "\\" in value or any(ord(char) < 33 for char in value):
        raise ValueError("DATABASE_URL contains whitespace or invalid URL characters")
    parsed = urlsplit(value)
    if parsed.scheme not in _PRODUCTION_DATABASE_SCHEMES:
        raise ValueError("DATABASE_URL must use PostgreSQL in production")
    if not parsed.hostname or parsed.path in ("", "/"):
        raise ValueError("DATABASE_URL must include a host and database name")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("DATABASE_URL contains an invalid port") from exc
    if parsed.fragment:
        raise ValueError("DATABASE_URL must not contain a URL fragment")
    ssl_modes = parse_qs(parsed.query, keep_blank_values=True).get("sslmode", [])
    if len(ssl_modes) != 1 or ssl_modes[0] not in {
        "require",
        "verify-ca",
        "verify-full",
    }:
        raise ValueError(
            "DATABASE_URL must set sslmode=require, verify-ca, or verify-full in production"
        )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", allow_inf_nan=False)

    database_url: str
    supabase_jwt_secret: str
    # Needed to fetch JWKS for ES256-signed Supabase access tokens.
    supabase_url: str = ""
    allowed_origins: str = "http://localhost:3000"
    # Canonical browser URL used for redirects and public links. Keep this
    # separate from the CORS allow-list, which may contain multiple origins.
    frontend_url: str = "http://localhost:3000"
    environment: Literal["development", "test", "production"] = "development"
    anthropic_api_key: str
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_pool_timeout: float = Field(default=10.0, gt=0, le=120)
    database_connect_timeout: int = Field(default=10, ge=1, le=30)

    # Gmail OAuth. Restricted scope (gmail.readonly) — fine for test users,
    # needs a CASA assessment before real users.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://127.0.0.1:8000/gmail/callback"
    # Fernet key encrypting stored refresh tokens at rest. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: str = ""

    @model_validator(mode="after")
    def validate_production_urls(self) -> "Settings":
        if self.environment != "production":
            return self

        _validate_production_database_url(self.database_url)
        if len(self.supabase_jwt_secret.strip()) < 32:
            raise ValueError(
                "SUPABASE_JWT_SECRET must contain at least 32 characters in production"
            )
        if not self.anthropic_api_key.strip():
            raise ValueError("ANTHROPIC_API_KEY must not be empty in production")

        _validate_https_url(
            self.supabase_url,
            label="SUPABASE_URL",
            origin_only=True,
        )
        _validate_https_url(
            self.frontend_url,
            label="FRONTEND_URL",
            origin_only=True,
        )
        _validate_https_url(
            self.google_redirect_uri,
            label="GOOGLE_REDIRECT_URI",
            origin_only=False,
        )
        redirect = urlsplit(self.google_redirect_uri)
        if redirect.query:
            raise ValueError("GOOGLE_REDIRECT_URI must not contain a query string")

        origins = [
            origin.strip()
            for origin in self.allowed_origins.split(",")
            if origin.strip()
        ]
        if not origins:
            raise ValueError("ALLOWED_ORIGINS must contain at least one HTTPS origin")
        if "*" in origins:
            raise ValueError(
                "ALLOWED_ORIGINS must not contain a wildcard in production"
            )
        for index, origin in enumerate(origins, start=1):
            _validate_https_url(
                origin,
                label=f"ALLOWED_ORIGINS entry {index}",
                origin_only=True,
            )
        if self.frontend_url not in origins:
            raise ValueError("FRONTEND_URL must also be present in ALLOWED_ORIGINS")

        configured_google_values = (
            bool(self.google_client_id),
            bool(self.google_client_secret),
        )
        if any(configured_google_values) and not all(configured_google_values):
            raise ValueError(
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be configured together"
            )
        return self


settings = Settings()
