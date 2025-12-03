"""
FastAPI application entry point.
Transaction Risk & Fraud Detection Engine
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.api.routes import router
from app.db.session import init_db
from app.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup
    logger.info("Starting Transaction Risk & Fraud Detection Engine...")
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="""
## Transaction Risk & Fraud Detection Engine

A backend service that accepts financial transactions, computes fraud risk scores (0-100),
logs reasons and evidence, and stores everything in a database.

### Features

- **Real-time Fraud Scoring**: Evaluate transactions instantly with multiple detection rules
- **Velocity Detection**: Track transaction frequency using sliding windows
- **Location Analysis**: Detect impossible travel scenarios using Haversine distance
- **Device Fingerprinting**: Track device changes for each user
- **Merchant Blacklisting**: Flag transactions from known fraudulent merchants
- **Duplicate Detection**: Identify duplicate transactions within short time windows

### Scoring Rules

1. **Amount Spike** (+30): Amount > 5x user's 30-day average
2. **Velocity Spike** (+25): ≥3 transactions in 60 seconds
3. **Velocity Unusual** (+15): ≥5 transactions in 10 minutes
4. **Location Mismatch** (+20): >500km distance in <12 hours
5. **Device Change** (+10): Different device from last known
6. **Merchant Blacklist** (+40): Transaction with blacklisted merchant
7. **Duplicate Transaction** (+35): Same amount + merchant in 30 seconds

Transactions with score ≥50 are flagged for review.
    """,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router, tags=["Fraud Detection"])


def custom_openapi():
    """Custom OpenAPI schema generator."""
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=app.description,
        routes=app.routes,
    )
    
    # Add additional metadata
    openapi_schema["info"]["x-logo"] = {
        "url": "https://fastapi.tiangolo.com/img/logo-margin/logo-teal.png"
    }
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.get("/", include_in_schema=False)
def root():
    """Root endpoint - redirects to docs."""
    return {
        "message": "Transaction Risk & Fraud Detection Engine",
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/health"
    }
