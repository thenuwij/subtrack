from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    supabase_jwt_secret: str
    # Needed to fetch JWKS for ES256-signed Supabase access tokens.
    supabase_url: str = ""
    allowed_origins: str = "http://localhost:3000"
    environment: str = "development"
    anthropic_api_key: str

    class Config:
        env_file = ".env"

settings = Settings()