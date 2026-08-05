from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    supabase_jwt_secret: str
    # Needed to fetch JWKS for ES256-signed Supabase access tokens.
    supabase_url: str = ""
    allowed_origins: str = "http://localhost:3000"
    environment: str = "development"
    anthropic_api_key: str
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_pool_timeout: float = 10.0

    # Gmail OAuth. Restricted scope (gmail.readonly) — fine for test users,
    # needs a CASA assessment before real users.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://127.0.0.1:8000/gmail/callback"
    # Fernet key encrypting stored refresh tokens at rest. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
