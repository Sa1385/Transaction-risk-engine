"""
Unit tests for the scoring engine.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from app.scoring.engine import (
    ScoringEngine, TransactionInput, haversine_distance,
    evaluate_transaction, MERCHANT_BLACKLIST
)
from app.db.models import Transaction, User


class TestHaversineDistance:
    """Test the Haversine distance calculation."""
    
    def test_same_location(self):
        """Distance between same points should be 0."""
        distance = haversine_distance(12.9716, 77.5946, 12.9716, 77.5946)
        assert distance == 0
    
    def test_known_distance(self):
        """Test with known city distances."""
        # Bangalore to Mumbai ~980 km
        distance = haversine_distance(12.9716, 77.5946, 19.0760, 72.8777)
        assert 900 < distance < 1100
    
    def test_long_distance(self):
        """Test intercontinental distance."""
        # London to New York ~5570 km
        distance = haversine_distance(51.5074, -0.1278, 40.7128, -74.0060)
        assert 5400 < distance < 5700


class TestAmountSpike:
    """Test amount spike detection."""
    
    def test_amount_spike_detected(self, db_session, sample_user, sample_transactions):
        """Amount > 5x average should trigger spike."""
        tx_input = TransactionInput(
            transaction_id="tx_spike",
            user_id=sample_user.user_id,
            amount=600.0,  # 6x the average of 100
            currency="INR",
            merchant_id="m_normal",
            timestamp=datetime.utcnow(),
            location_lat=None,
            location_lng=None,
            device_id=None,
            metadata=None
        )
        
        with patch("app.scoring.engine.redis_client") as mock_redis:
            mock_redis.get_last_known.return_value = None
            mock_redis.get_transaction_count_in_window.return_value = 0
            mock_redis.check_duplicate_transaction.return_value = False
            
            result = evaluate_transaction(tx_input, db_session)
        
        assert "amount_spike" in result.reasons
        assert result.score >= 30
    
    def test_amount_spike_not_triggered(self, db_session, sample_user, sample_transactions):
        """Amount within normal range should not trigger spike."""
        tx_input = TransactionInput(
            transaction_id="tx_normal",
            user_id=sample_user.user_id,
            amount=150.0,  # 1.5x average - within threshold
            currency="INR",
            merchant_id="m_normal",
            timestamp=datetime.utcnow(),
            location_lat=None,
            location_lng=None,
            device_id=None,
            metadata=None
        )
        
        with patch("app.scoring.engine.redis_client") as mock_redis:
            mock_redis.get_last_known.return_value = None
            mock_redis.get_transaction_count_in_window.return_value = 0
            mock_redis.check_duplicate_transaction.return_value = False
            
            result = evaluate_transaction(tx_input, db_session)
        
        assert "amount_spike" not in result.reasons


class TestVelocitySpike:
    """Test velocity detection."""
    
    def test_velocity_spike_high(self, db_session, sample_user):
        """3+ transactions in 60 seconds should trigger velocity_spike."""
        tx_input = TransactionInput(
            transaction_id="tx_velocity",
            user_id=sample_user.user_id,
            amount=100.0,
            currency="INR",
            merchant_id="m_normal",
            timestamp=datetime.utcnow(),
            location_lat=None,
            location_lng=None,
            device_id=None,
            metadata=None
        )
        
        with patch("app.scoring.engine.redis_client") as mock_redis:
            mock_redis.get_last_known.return_value = None
            mock_redis.get_transaction_count_in_window.side_effect = lambda uid, window: 3 if window == 60 else 0
            mock_redis.check_duplicate_transaction.return_value = False
            
            result = evaluate_transaction(tx_input, db_session)
        
        assert "velocity_spike" in result.reasons
        assert result.score >= 25
    
    def test_velocity_unusual(self, db_session, sample_user):
        """5+ transactions in 10 minutes should trigger velocity_unusual."""
        tx_input = TransactionInput(
            transaction_id="tx_velocity_unusual",
            user_id=sample_user.user_id,
            amount=100.0,
            currency="INR",
            merchant_id="m_normal",
            timestamp=datetime.utcnow(),
            location_lat=None,
            location_lng=None,
            device_id=None,
            metadata=None
        )
        
        with patch("app.scoring.engine.redis_client") as mock_redis:
            mock_redis.get_last_known.return_value = None
            # 2 in 60s (not spike), but 5 in 10 min (unusual)
            mock_redis.get_transaction_count_in_window.side_effect = lambda uid, window: 2 if window == 60 else 5
            mock_redis.check_duplicate_transaction.return_value = False
            
            result = evaluate_transaction(tx_input, db_session)
        
        assert "velocity_unusual" in result.reasons
        assert result.score >= 15


class TestLocationMismatch:
    """Test location mismatch detection."""
    
    def test_location_mismatch_detected(self, db_session, sample_user):
        """Location change > 500km in < 12 hours should trigger."""
        tx_input = TransactionInput(
            transaction_id="tx_location",
            user_id=sample_user.user_id,
            amount=100.0,
            currency="INR",
            merchant_id="m_normal",
            timestamp=datetime.utcnow(),
            location_lat=40.7128,  # New York
            location_lng=-74.0060,
            device_id="dev_1",
            metadata=None
        )
        
        # Last known location was Bangalore, 2 hours ago
        last_known = {
            "device_id": "dev_1",
            "lat": 12.9716,  # Bangalore
            "lng": 77.5946,
            "last_timestamp": (datetime.utcnow() - timedelta(hours=2)).isoformat()
        }
        
        with patch("app.scoring.engine.redis_client") as mock_redis:
            mock_redis.get_last_known.return_value = last_known
            mock_redis.get_transaction_count_in_window.return_value = 0
            mock_redis.check_duplicate_transaction.return_value = False
            
            result = evaluate_transaction(tx_input, db_session)
        
        assert "location_mismatch" in result.reasons
        assert result.score >= 20
    
    def test_location_mismatch_not_triggered_slow_travel(self, db_session, sample_user):
        """Location change > 500km in > 12 hours should not trigger."""
        tx_input = TransactionInput(
            transaction_id="tx_location_ok",
            user_id=sample_user.user_id,
            amount=100.0,
            currency="INR",
            merchant_id="m_normal",
            timestamp=datetime.utcnow(),
            location_lat=40.7128,  # New York
            location_lng=-74.0060,
            device_id="dev_1",
            metadata=None
        )
        
        # Last known location was Bangalore, 24 hours ago
        last_known = {
            "device_id": "dev_1",
            "lat": 12.9716,
            "lng": 77.5946,
            "last_timestamp": (datetime.utcnow() - timedelta(hours=24)).isoformat()
        }
        
        with patch("app.scoring.engine.redis_client") as mock_redis:
            mock_redis.get_last_known.return_value = last_known
            mock_redis.get_transaction_count_in_window.return_value = 0
            mock_redis.check_duplicate_transaction.return_value = False
            
            result = evaluate_transaction(tx_input, db_session)
        
        assert "location_mismatch" not in result.reasons


class TestDeviceChange:
    """Test device change detection."""
    
    def test_device_change_detected(self, db_session, sample_user):
        """Different device from last known should trigger."""
        tx_input = TransactionInput(
            transaction_id="tx_device",
            user_id=sample_user.user_id,
            amount=100.0,
            currency="INR",
            merchant_id="m_normal",
            timestamp=datetime.utcnow(),
            location_lat=None,
            location_lng=None,
            device_id="new_device",
            metadata=None
        )
        
        last_known = {
            "device_id": "old_device",
            "lat": None,
            "lng": None,
            "last_timestamp": datetime.utcnow().isoformat()
        }
        
        with patch("app.scoring.engine.redis_client") as mock_redis:
            mock_redis.get_last_known.return_value = last_known
            mock_redis.get_transaction_count_in_window.return_value = 0
            mock_redis.check_duplicate_transaction.return_value = False
            
            result = evaluate_transaction(tx_input, db_session)
        
        assert "device_change" in result.reasons
        assert result.score >= 10
    
    def test_same_device_no_trigger(self, db_session, sample_user):
        """Same device should not trigger."""
        tx_input = TransactionInput(
            transaction_id="tx_same_device",
            user_id=sample_user.user_id,
            amount=100.0,
            currency="INR",
            merchant_id="m_normal",
            timestamp=datetime.utcnow(),
            location_lat=None,
            location_lng=None,
            device_id="dev_1",
            metadata=None
        )
        
        last_known = {
            "device_id": "dev_1",
            "lat": None,
            "lng": None,
            "last_timestamp": datetime.utcnow().isoformat()
        }
        
        with patch("app.scoring.engine.redis_client") as mock_redis:
            mock_redis.get_last_known.return_value = last_known
            mock_redis.get_transaction_count_in_window.return_value = 0
            mock_redis.check_duplicate_transaction.return_value = False
            
            result = evaluate_transaction(tx_input, db_session)
        
        assert "device_change" not in result.reasons


class TestDuplicateTransaction:
    """Test duplicate transaction detection."""
    
    def test_duplicate_detected(self, db_session, sample_user):
        """Same amount + merchant within 30s should trigger."""
        tx_input = TransactionInput(
            transaction_id="tx_dup",
            user_id=sample_user.user_id,
            amount=100.0,
            currency="INR",
            merchant_id="m_normal",
            timestamp=datetime.utcnow(),
            location_lat=None,
            location_lng=None,
            device_id=None,
            metadata=None
        )
        
        with patch("app.scoring.engine.redis_client") as mock_redis:
            mock_redis.get_last_known.return_value = None
            mock_redis.get_transaction_count_in_window.return_value = 0
            mock_redis.check_duplicate_transaction.return_value = True  # Duplicate found!
            
            result = evaluate_transaction(tx_input, db_session)
        
        assert "duplicate_transaction" in result.reasons
        assert result.score >= 35


class TestMerchantBlacklist:
    """Test merchant blacklist detection."""
    
    def test_blacklisted_merchant(self, db_session, sample_user):
        """Transaction with blacklisted merchant should trigger."""
        tx_input = TransactionInput(
            transaction_id="tx_blacklist",
            user_id=sample_user.user_id,
            amount=100.0,
            currency="INR",
            merchant_id="m_blacklisted",  # In blacklist
            timestamp=datetime.utcnow(),
            location_lat=None,
            location_lng=None,
            device_id=None,
            metadata=None
        )
        
        with patch("app.scoring.engine.redis_client") as mock_redis:
            mock_redis.get_last_known.return_value = None
            mock_redis.get_transaction_count_in_window.return_value = 0
            mock_redis.check_duplicate_transaction.return_value = False
            
            result = evaluate_transaction(tx_input, db_session)
        
        assert "merchant_blacklist" in result.reasons
        assert result.score >= 40
    
    def test_fraud_merchant_blacklisted(self, db_session, sample_user):
        """Test the 'fraud_merchant' is also blacklisted."""
        tx_input = TransactionInput(
            transaction_id="tx_fraud_merchant",
            user_id=sample_user.user_id,
            amount=100.0,
            currency="INR",
            merchant_id="fraud_merchant",
            timestamp=datetime.utcnow(),
            location_lat=None,
            location_lng=None,
            device_id=None,
            metadata=None
        )
        
        with patch("app.scoring.engine.redis_client") as mock_redis:
            mock_redis.get_last_known.return_value = None
            mock_redis.get_transaction_count_in_window.return_value = 0
            mock_redis.check_duplicate_transaction.return_value = False
            
            result = evaluate_transaction(tx_input, db_session)
        
        assert "merchant_blacklist" in result.reasons


class TestScoreCapping:
    """Test that scores are properly capped."""
    
    def test_score_caps_at_100(self, db_session, sample_user, sample_transactions):
        """Score should never exceed 100 even with multiple triggers."""
        tx_input = TransactionInput(
            transaction_id="tx_max",
            user_id=sample_user.user_id,
            amount=600.0,  # +30 amount spike
            currency="INR",
            merchant_id="m_blacklisted",  # +40 blacklist
            timestamp=datetime.utcnow(),
            location_lat=40.7128,
            location_lng=-74.0060,
            device_id="new_device",
            metadata=None
        )
        
        last_known = {
            "device_id": "old_device",
            "lat": 12.9716,
            "lng": 77.5946,
            "last_timestamp": (datetime.utcnow() - timedelta(hours=1)).isoformat()
        }
        
        with patch("app.scoring.engine.redis_client") as mock_redis:
            mock_redis.get_last_known.return_value = last_known
            mock_redis.get_transaction_count_in_window.side_effect = lambda uid, window: 5
            mock_redis.check_duplicate_transaction.return_value = True
            
            result = evaluate_transaction(tx_input, db_session)
        
        assert result.score <= 100
        assert result.score >= 0
    
    def test_score_minimum_is_zero(self, db_session, sample_user):
        """Score should never go below 0."""
        tx_input = TransactionInput(
            transaction_id="tx_clean",
            user_id=sample_user.user_id,
            amount=100.0,
            currency="INR",
            merchant_id="m_normal",
            timestamp=datetime.utcnow(),
            location_lat=None,
            location_lng=None,
            device_id=None,
            metadata=None
        )
        
        with patch("app.scoring.engine.redis_client") as mock_redis:
            mock_redis.get_last_known.return_value = None
            mock_redis.get_transaction_count_in_window.return_value = 0
            mock_redis.check_duplicate_transaction.return_value = False
            
            result = evaluate_transaction(tx_input, db_session)
        
        assert result.score >= 0


class TestIdempotency:
    """Test that same input produces same output."""
    
    def test_idempotency_returns_same_results(self, db_session, sample_user):
        """Same transaction evaluated twice should return same results."""
        tx_input = TransactionInput(
            transaction_id="tx_idemp",
            user_id=sample_user.user_id,
            amount=100.0,
            currency="INR",
            merchant_id="m_normal",
            timestamp=datetime.utcnow(),
            location_lat=12.9716,
            location_lng=77.5946,
            device_id="dev_1",
            metadata=None
        )
        
        with patch("app.scoring.engine.redis_client") as mock_redis:
            mock_redis.get_last_known.return_value = None
            mock_redis.get_transaction_count_in_window.return_value = 0
            mock_redis.check_duplicate_transaction.return_value = False
            
            result1 = evaluate_transaction(tx_input, db_session)
            result2 = evaluate_transaction(tx_input, db_session)
        
        assert result1.score == result2.score
        assert result1.reasons == result2.reasons
