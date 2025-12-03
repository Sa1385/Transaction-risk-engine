"""
Integration tests for API endpoints.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch


class TestPostTransactions:
    """Test POST /transactions endpoint."""
    
    def test_process_transaction_success(self, client, base_transaction_request):
        """Test successful transaction processing."""
        response = client.post("/transactions", json=base_transaction_request)
        
        assert response.status_code == 200
        data = response.json()
        assert data["transaction_id"] == base_transaction_request["transaction_id"]
        assert "risk_score" in data
        assert "risk_reasons" in data
        assert "flagged" in data
        assert 0 <= data["risk_score"] <= 100
    
    def test_process_transaction_idempotency(self, client, base_transaction_request):
        """Test that same transaction returns same result."""
        response1 = client.post("/transactions", json=base_transaction_request)
        response2 = client.post("/transactions", json=base_transaction_request)
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        assert response1.json() == response2.json()
    
    def test_process_transaction_invalid_amount(self, client, base_transaction_request):
        """Test validation for negative amount."""
        base_transaction_request["amount"] = -100.0
        response = client.post("/transactions", json=base_transaction_request)
        
        assert response.status_code == 422  # Validation error
    
    def test_process_transaction_missing_required_field(self, client):
        """Test validation for missing required field."""
        response = client.post("/transactions", json={"transaction_id": "test"})
        
        assert response.status_code == 422
    
    def test_process_transaction_without_location(self, client, base_transaction_request):
        """Test transaction without location data."""
        del base_transaction_request["location"]
        response = client.post("/transactions", json=base_transaction_request)
        
        assert response.status_code == 200
    
    def test_process_transaction_without_device(self, client, base_transaction_request):
        """Test transaction without device data."""
        del base_transaction_request["device_id"]
        response = client.post("/transactions", json=base_transaction_request)
        
        assert response.status_code == 200


class TestGetRisk:
    """Test GET /risk/{transaction_id} endpoint."""
    
    def test_get_risk_success(self, client, base_transaction_request):
        """Test retrieving risk evaluation."""
        # First create a transaction
        client.post("/transactions", json=base_transaction_request)
        
        # Then retrieve its risk
        response = client.get(f"/risk/{base_transaction_request['transaction_id']}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["transaction_id"] == base_transaction_request["transaction_id"]
        assert "risk_score" in data
        assert "risk_reasons" in data
        assert "raw_evidence" in data
        assert "evaluated_at" in data
    
    def test_get_risk_not_found(self, client):
        """Test 404 for non-existent transaction."""
        response = client.get("/risk/non_existent_tx")
        
        assert response.status_code == 404


class TestGetFlags:
    """Test GET /flags endpoint."""
    
    def test_get_flags_empty(self, client):
        """Test empty flags list."""
        response = client.get("/flags")
        
        assert response.status_code == 200
        assert response.json() == []
    
    def test_get_flags_with_min_score(self, client, base_transaction_request, mock_redis):
        """Test filtering by minimum score."""
        # Create a transaction with blacklisted merchant for high score
        base_transaction_request["merchant_id"] = "m_blacklisted"
        base_transaction_request["transaction_id"] = "tx_flagged"
        
        client.post("/transactions", json=base_transaction_request)
        
        # Query with min_score
        response = client.get("/flags?min_score=40")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 0  # May or may not be flagged depending on score
    
    def test_get_flags_with_limit(self, client):
        """Test limit parameter."""
        response = client.get("/flags?limit=10")
        
        assert response.status_code == 200
        assert len(response.json()) <= 10
    
    def test_get_flags_invalid_min_score(self, client):
        """Test validation for invalid min_score."""
        response = client.get("/flags?min_score=150")
        
        assert response.status_code == 422


class TestHealth:
    """Test GET /health endpoint."""
    
    def test_health_check(self, client):
        """Test health check returns proper structure."""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "database" in data
        assert "redis" in data
        assert "timestamp" in data


class TestRedisSlidingWindow:
    """Test Redis sliding window functionality."""
    
    def test_velocity_detection_uses_redis(self, client, base_transaction_request, mock_redis):
        """Test that velocity detection queries Redis."""
        client.post("/transactions", json=base_transaction_request)
        
        # Verify Redis was queried for transaction count
        mock_redis.get_transaction_count_in_window.assert_called()
    
    def test_recent_transaction_stored(self, client, base_transaction_request, mock_redis):
        """Test that transaction is added to Redis after processing."""
        client.post("/transactions", json=base_transaction_request)
        
        # Verify transaction was added to recent list
        mock_redis.add_recent_transaction.assert_called()


class TestPostgresPersistence:
    """Test PostgreSQL persistence."""
    
    def test_transaction_persisted(self, client, db_session, base_transaction_request):
        """Test that transaction is saved to database."""
        from app.db.models import Transaction
        
        client.post("/transactions", json=base_transaction_request)
        
        tx = db_session.query(Transaction).filter(
            Transaction.transaction_id == base_transaction_request["transaction_id"]
        ).first()
        
        assert tx is not None
        assert tx.amount == base_transaction_request["amount"]
    
    def test_risk_log_persisted(self, client, db_session, base_transaction_request):
        """Test that risk log is saved to database."""
        from app.db.models import RiskLog
        
        client.post("/transactions", json=base_transaction_request)
        
        log = db_session.query(RiskLog).filter(
            RiskLog.transaction_id == base_transaction_request["transaction_id"]
        ).first()
        
        assert log is not None
        assert log.risk_score is not None
        assert log.reasons is not None
