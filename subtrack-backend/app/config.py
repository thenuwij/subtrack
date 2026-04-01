from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    supabase_jwt_secret: str
    allowed_origins: str = "http://localhost:3000"
    environment: str = "development"

    class Config:
        env_file = ".env"

settings = Settings()