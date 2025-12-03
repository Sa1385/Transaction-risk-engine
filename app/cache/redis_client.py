"""
Redis caching layer for fraud detection.
Handles sliding windows, last known device/location tracking.
"""
import redis
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

from app.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Redis client wrapper for fraud detection caching."""
    
    # Key prefixes
    LAST_KNOWN_PREFIX = "LAST_KNOWN:"
    RECENT_TX_PREFIX = "RECENT_TX:"
    TX_HASH_PREFIX = "TX_HASH:"  # For duplicate detection
    
    def __init__(self):
        self._client: Optional[redis.Redis] = None
    
    @property
    def client(self) -> redis.Redis:
        """Lazy initialization of Redis client."""
        if self._client is None:
            self._client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
        return self._client
    
    def ping(self) -> bool:
        """Check Redis connectivity."""
        try:
            return self.client.ping()
        except Exception as e:
            logger.error(f"Redis ping failed: {e}")
            return False
    
    def get_last_known(self, user_id: str) -> Optional[Dict]:
        """
        Get last known device and location for a user.
        Returns: {device_id, lat, lng, last_timestamp}
        """
        try:
            key = f"{self.LAST_KNOWN_PREFIX}{user_id}"
            data = self.client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Error getting last known for {user_id}: {e}")
            return None
    
    def set_last_known(
        self, 
        user_id: str, 
        device_id: str, 
        lat: Optional[float], 
        lng: Optional[float],
        timestamp: datetime
    ):
        """Update last known device and location for a user."""
        try:
            key = f"{self.LAST_KNOWN_PREFIX}{user_id}"
            data = {
                "device_id": device_id,
                "lat": lat,
                "lng": lng,
                "last_timestamp": timestamp.isoformat()
            }
            # Keep for 30 days
            self.client.setex(key, timedelta(days=30), json.dumps(data))
        except Exception as e:
            logger.error(f"Error setting last known for {user_id}: {e}")
    
    def add_recent_transaction(self, user_id: str, timestamp: datetime, tx_id: str):
        """
        Add a transaction timestamp to user's recent transaction set.
        Uses sorted set with timestamp as score for efficient range queries.
        """
        try:
            key = f"{self.RECENT_TX_PREFIX}{user_id}"
            score = timestamp.timestamp()
            # Store tx_id as member with timestamp as score
            self.client.zadd(key, {tx_id: score})
            # Clean up old entries (keep last 24 hours)
            cutoff = (datetime.utcnow() - timedelta(hours=24)).timestamp()
            self.client.zremrangebyscore(key, "-inf", cutoff)
            # Set expiry on the key
            self.client.expire(key, 86400)  # 24 hours
        except Exception as e:
            logger.error(f"Error adding recent tx for {user_id}: {e}")
    
    def get_transaction_count_in_window(
        self, 
        user_id: str, 
        window_seconds: int
    ) -> int:
        """
        Get count of transactions in the last N seconds.
        Used for velocity detection.
        """
        try:
            key = f"{self.RECENT_TX_PREFIX}{user_id}"
            now = datetime.utcnow().timestamp()
            start = now - window_seconds
            return self.client.zcount(key, start, now)
        except Exception as e:
            logger.error(f"Error getting tx count for {user_id}: {e}")
            return 0
    
    def get_recent_transactions(
        self, 
        user_id: str, 
        window_seconds: int
    ) -> List[Tuple[str, float]]:
        """Get recent transactions with their timestamps."""
        try:
            key = f"{self.RECENT_TX_PREFIX}{user_id}"
            now = datetime.utcnow().timestamp()
            start = now - window_seconds
            # Returns list of (tx_id, score) tuples
            return self.client.zrangebyscore(key, start, now, withscores=True)
        except Exception as e:
            logger.error(f"Error getting recent txs for {user_id}: {e}")
            return []
    
    def check_duplicate_transaction(
        self, 
        user_id: str, 
        merchant_id: str, 
        amount: float,
        window_seconds: int = 30
    ) -> bool:
        """
        Check if a similar transaction exists within the time window.
        Returns True if duplicate found.
        """
        try:
            # Create a hash of the transaction signature
            tx_hash = f"{user_id}:{merchant_id}:{amount}"
            key = f"{self.TX_HASH_PREFIX}{tx_hash}"
            
            # Check if this exact combination exists
            if self.client.exists(key):
                return True
            
            # Store with short expiry for duplicate detection
            self.client.setex(key, window_seconds, "1")
            return False
        except Exception as e:
            logger.error(f"Error checking duplicate tx: {e}")
            return False
    
    def health_check(self) -> dict:
        """Return Redis health status."""
        try:
            if self.ping():
                info = self.client.info("server")
                return {
                    "status": "healthy",
                    "redis_version": info.get("redis_version", "unknown"),
                    "connected_clients": self.client.info("clients").get("connected_clients", 0)
                }
            return {"status": "unhealthy", "message": "Ping failed"}
        except Exception as e:
            return {"status": "unhealthy", "message": str(e)}


# Singleton instance
redis_client = RedisClient()
