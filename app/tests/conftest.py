"""
PyTest configuration and fixtures.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi.testclient import TestClient

from app.main import app
from app.db.models import Base, User, Transaction
from app.db.session import get_db
from app.cache.redis_client import RedisClient


# Test database (in-memory SQLite)
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    Base.metadata.create_all(bind=engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def mock_redis():
    """Mock Redis client for testing."""
    mock_client = MagicMock(spec=RedisClient)
    
    # Default mock returns
    mock_client.ping.return_value = True
    mock_client.get_last_known.return_value = None
    mock_client.get_transaction_count_in_window.return_value = 0
    mock_client.check_duplicate_transaction.return_value = False
    mock_client.health_check.return_value = {"status": "healthy"}
    
    return mock_client


@pytest.fixture(scope="function")
def client(db_session, mock_redis):
    """Create test client with mocked dependencies."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    
    with patch("app.api.routes.redis_client", mock_redis):
        with patch("app.scoring.engine.redis_client", mock_redis):
            with TestClient(app) as test_client:
                yield test_client
    
    app.dependency_overrides.clear()


@pytest.fixture
def sample_user(db_session):
    """Create a sample user."""
    user = User(user_id="test_user")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def sample_transactions(db_session, sample_user):
    """Create sample historical transactions."""
    transactions = []
    base_time = datetime.utcnow() - timedelta(days=15)
    
    for i in range(10):
        tx = Transaction(
            transaction_id=f"hist_tx_{i}",
            user_id=sample_user.user_id,
            amount=100.0,  # Average of 100
            currency="INR",
            merchant_id="m_normal",
            timestamp=base_time + timedelta(days=i),
            location_lat=12.9716,
            location_lng=77.5946,
            device_id="dev_1"
        )
        transactions.append(tx)
        db_session.add(tx)
    
    db_session.commit()
    return transactions


@pytest.fixture
def base_transaction_request():
    """Base transaction request for testing."""
    return {
        "transaction_id": "tx_test_001",
        "user_id": "test_user",
        "amount": 100.0,
        "currency": "INR",
        "merchant_id": "m_normal",
        "timestamp": datetime.utcnow().isoformat(),
        "location": {"lat": 12.9716, "lng": 77.5946},
        "device_id": "dev_1",
        "metadata": {"channel": "web"}
    }
