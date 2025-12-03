"""
Database session management.
Provides async database connection and session handling.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
import logging

from app.config import settings
from app.db.models import Base

logger = logging.getLogger(__name__)

# Create engine with connection pooling
engine = create_engine(
    settings.DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Verify connections before use
    echo=settings.DEBUG
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}")
        raise


def get_db() -> Session:
    """
    Dependency for FastAPI routes.
    Yields a database session and ensures cleanup.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context():
    """Context manager for database sessions outside of FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_health() -> dict:
    """Check database connectivity and return health status."""
    try:
        with get_db_context() as db:
            db.execute("SELECT 1")
        return {"status": "healthy", "message": "Database connection successful"}
    except Exception as e:
        return {"status": "unhealthy", "message": str(e)}
