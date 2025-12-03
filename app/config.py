"""
Application configuration settings.
Loads from environment variables with sensible defaults.
"""
import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database settings
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@postgres:5432/fraud_detection"
    )
    
    # Redis settings
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    
    # Application settings
    APP_NAME: str = "Transaction Risk & Fraud Detection Engine"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    
    # Scoring thresholds
    FLAG_THRESHOLD: int = 50  # Transactions with score >= this are flagged
    
    class Config:
        env_file = ".env"
        extra = "allow"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
