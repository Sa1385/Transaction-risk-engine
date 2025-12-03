"""
Fraud Scoring Engine - Core risk assessment logic.
Implements all fraud detection rules and scoring.
"""
import math
import logging
from datetime import datetime, timedelta
from typing import Tuple, List, Dict, Any, Optional
from dataclasses import dataclass

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.models import Transaction
from app.cache.redis_client import redis_client

logger = logging.getLogger(__name__)

# Merchant blacklist - static list of known fraudulent merchants
MERCHANT_BLACKLIST = frozenset(["m_blacklisted", "fraud_merchant"])


@dataclass
class TransactionInput:
    """Input data for transaction evaluation."""
    transaction_id: str
    user_id: str
    amount: float
    currency: str
    merchant_id: str
    timestamp: datetime
    location_lat: Optional[float]
    location_lng: Optional[float]
    device_id: Optional[str]
    metadata: Optional[Dict[str, Any]]


@dataclass
class RiskResult:
    """Result of risk evaluation."""
    score: int
    reasons: List[str]
    evidence: Dict[str, Any]
    flagged: bool


def haversine_distance(
    lat1: float, lng1: float, 
    lat2: float, lng2: float
) -> float:
    """
    Calculate the great circle distance between two points on Earth.
    Returns distance in kilometers.
    """
    R = 6371  # Earth's radius in kilometers
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    
    a = (math.sin(delta_lat / 2) ** 2 + 
         math.cos(lat1_rad) * math.cos(lat2_rad) * 
         math.sin(delta_lng / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def get_user_average_amount(db: Session, user_id: str, days: int = 30) -> Optional[float]:
    """
    Calculate user's average transaction amount over the last N days.
    Returns None if no transactions found.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    result = db.query(func.avg(Transaction.amount)).filter(
        Transaction.user_id == user_id,
        Transaction.timestamp >= cutoff
    ).scalar()
    
    return float(result) if result else None


class ScoringEngine:
    """
    Main scoring engine that evaluates transactions for fraud risk.
    Implements all detection rules and combines scores.
    """
    
    # Scoring constants
    AMOUNT_SPIKE_MULTIPLIER = 5.0
    AMOUNT_SPIKE_SCORE = 30
    
    VELOCITY_HIGH_COUNT = 3
    VELOCITY_HIGH_WINDOW = 60  # seconds
    VELOCITY_HIGH_SCORE = 25
    
    VELOCITY_UNUSUAL_COUNT = 5
    VELOCITY_UNUSUAL_WINDOW = 600  # 10 minutes
    VELOCITY_UNUSUAL_SCORE = 15
    
    LOCATION_DISTANCE_THRESHOLD = 500  # km
    LOCATION_TIME_THRESHOLD = 12  # hours
    LOCATION_MISMATCH_SCORE = 20
    
    DEVICE_CHANGE_SCORE = 10
    
    MERCHANT_BLACKLIST_SCORE = 40
    
    DUPLICATE_WINDOW = 30  # seconds
    DUPLICATE_SCORE = 35
    
    FLAG_THRESHOLD = 50
    
    def __init__(self, db: Session):
        self.db = db
    
    def evaluate_transaction(self, tx: TransactionInput) -> RiskResult:
        """
        Main evaluation function - runs all checks and returns risk result.
        """
        score = 0
        reasons = []
        evidence = {}
        
        # Run all checks
        score, reasons, evidence = self._check_amount_spike(tx, score, reasons, evidence)
        score, reasons, evidence = self._check_velocity(tx, score, reasons, evidence)
        score, reasons, evidence = self._check_location_mismatch(tx, score, reasons, evidence)
        score, reasons, evidence = self._check_device_change(tx, score, reasons, evidence)
        score, reasons, evidence = self._check_merchant_blacklist(tx, score, reasons, evidence)
        score, reasons, evidence = self._check_duplicate_transaction(tx, score, reasons, evidence)
        
        # Clamp score between 0-100
        final_score = max(0, min(100, score))
        
        # Determine if flagged
        flagged = final_score >= self.FLAG_THRESHOLD
        
        return RiskResult(
            score=final_score,
            reasons=reasons,
            evidence=evidence,
            flagged=flagged
        )
    
    def _check_amount_spike(
        self, tx: TransactionInput, 
        score: int, reasons: List[str], evidence: Dict
    ) -> Tuple[int, List[str], Dict]:
        """
        Rule 1: Amount Spike
        If amount > 5x average user amount (last 30 days) -> +30 score
        """
        avg_amount = get_user_average_amount(self.db, tx.user_id, days=30)
        
        if avg_amount is not None and avg_amount > 0:
            threshold = avg_amount * self.AMOUNT_SPIKE_MULTIPLIER
            if tx.amount > threshold:
                score += self.AMOUNT_SPIKE_SCORE
                reasons.append("amount_spike")
                evidence["amount_spike"] = {
                    "current_amount": tx.amount,
                    "average_amount": round(avg_amount, 2),
                    "threshold": round(threshold, 2),
                    "multiplier": round(tx.amount / avg_amount, 2)
                }
        else:
            evidence["amount_spike"] = {
                "status": "no_history",
                "message": "No previous transactions to compare"
            }
        
        return score, reasons, evidence
    
    def _check_velocity(
        self, tx: TransactionInput,
        score: int, reasons: List[str], evidence: Dict
    ) -> Tuple[int, List[str], Dict]:
        """
        Rule 2: Velocity Check
        - If ≥3 transactions in last 60 seconds -> +25 ("velocity_spike")
        - Else if ≥5 in last 10 minutes -> +15 ("velocity_unusual")
        """
        # Check high velocity (60 seconds)
        count_60s = redis_client.get_transaction_count_in_window(
            tx.user_id, self.VELOCITY_HIGH_WINDOW
        )
        
        if count_60s >= self.VELOCITY_HIGH_COUNT:
            score += self.VELOCITY_HIGH_SCORE
            reasons.append("velocity_spike")
            evidence["velocity"] = {
                "type": "velocity_spike",
                "count_60s": count_60s,
                "threshold": self.VELOCITY_HIGH_COUNT
            }
        else:
            # Check unusual velocity (10 minutes)
            count_10m = redis_client.get_transaction_count_in_window(
                tx.user_id, self.VELOCITY_UNUSUAL_WINDOW
            )
            
            if count_10m >= self.VELOCITY_UNUSUAL_COUNT:
                score += self.VELOCITY_UNUSUAL_SCORE
                reasons.append("velocity_unusual")
                evidence["velocity"] = {
                    "type": "velocity_unusual",
                    "count_10m": count_10m,
                    "threshold": self.VELOCITY_UNUSUAL_COUNT
                }
            else:
                evidence["velocity"] = {
                    "status": "normal",
                    "count_60s": count_60s,
                    "count_10m": count_10m
                }
        
        return score, reasons, evidence
    
    def _check_location_mismatch(
        self, tx: TransactionInput,
        score: int, reasons: List[str], evidence: Dict
    ) -> Tuple[int, List[str], Dict]:
        """
        Rule 3: Location Mismatch
        If distance > 500 km AND time < 12 hours -> +20 ("location_mismatch")
        """
        if tx.location_lat is None or tx.location_lng is None:
            evidence["location"] = {"status": "no_location_provided"}
            return score, reasons, evidence
        
        last_known = redis_client.get_last_known(tx.user_id)
        
        if last_known and last_known.get("lat") and last_known.get("lng"):
            last_lat = last_known["lat"]
            last_lng = last_known["lng"]
            last_timestamp = datetime.fromisoformat(last_known["last_timestamp"])
            
            # Calculate distance
            distance = haversine_distance(
                last_lat, last_lng,
                tx.location_lat, tx.location_lng
            )
            
            # Calculate time difference in hours
            time_diff = (tx.timestamp - last_timestamp).total_seconds() / 3600
            
            if distance > self.LOCATION_DISTANCE_THRESHOLD and time_diff < self.LOCATION_TIME_THRESHOLD:
                score += self.LOCATION_MISMATCH_SCORE
                reasons.append("location_mismatch")
                evidence["location"] = {
                    "type": "mismatch",
                    "distance_km": round(distance, 2),
                    "time_diff_hours": round(time_diff, 2),
                    "last_location": {"lat": last_lat, "lng": last_lng},
                    "current_location": {"lat": tx.location_lat, "lng": tx.location_lng}
                }
            else:
                evidence["location"] = {
                    "status": "normal",
                    "distance_km": round(distance, 2),
                    "time_diff_hours": round(time_diff, 2)
                }
        else:
            evidence["location"] = {"status": "no_previous_location"}
        
        return score, reasons, evidence
    
    def _check_device_change(
        self, tx: TransactionInput,
        score: int, reasons: List[str], evidence: Dict
    ) -> Tuple[int, List[str], Dict]:
        """
        Rule 4: Device Change
        If device_id != last known device -> +10 ("device_change")
        """
        if tx.device_id is None:
            evidence["device"] = {"status": "no_device_provided"}
            return score, reasons, evidence
        
        last_known = redis_client.get_last_known(tx.user_id)
        
        if last_known and last_known.get("device_id"):
            last_device = last_known["device_id"]
            
            if tx.device_id != last_device:
                score += self.DEVICE_CHANGE_SCORE
                reasons.append("device_change")
                evidence["device"] = {
                    "type": "changed",
                    "previous_device": last_device,
                    "current_device": tx.device_id
                }
            else:
                evidence["device"] = {
                    "status": "same_device",
                    "device_id": tx.device_id
                }
        else:
            evidence["device"] = {"status": "first_device", "device_id": tx.device_id}
        
        return score, reasons, evidence
    
    def _check_merchant_blacklist(
        self, tx: TransactionInput,
        score: int, reasons: List[str], evidence: Dict
    ) -> Tuple[int, List[str], Dict]:
        """
        Rule 5: Merchant Blacklist
        If merchant in blacklist -> +40 ("merchant_blacklist")
        """
        if tx.merchant_id in MERCHANT_BLACKLIST:
            score += self.MERCHANT_BLACKLIST_SCORE
            reasons.append("merchant_blacklist")
            evidence["merchant"] = {
                "type": "blacklisted",
                "merchant_id": tx.merchant_id
            }
        else:
            evidence["merchant"] = {
                "status": "not_blacklisted",
                "merchant_id": tx.merchant_id
            }
        
        return score, reasons, evidence
    
    def _check_duplicate_transaction(
        self, tx: TransactionInput,
        score: int, reasons: List[str], evidence: Dict
    ) -> Tuple[int, List[str], Dict]:
        """
        Rule 6: Duplicate Transaction
        Same amount + merchant within last 30s -> +35 ("duplicate_transaction")
        """
        is_duplicate = redis_client.check_duplicate_transaction(
            tx.user_id,
            tx.merchant_id,
            tx.amount,
            self.DUPLICATE_WINDOW
        )
        
        if is_duplicate:
            score += self.DUPLICATE_SCORE
            reasons.append("duplicate_transaction")
            evidence["duplicate"] = {
                "type": "detected",
                "window_seconds": self.DUPLICATE_WINDOW,
                "merchant_id": tx.merchant_id,
                "amount": tx.amount
            }
        else:
            evidence["duplicate"] = {"status": "not_duplicate"}
        
        return score, reasons, evidence


def evaluate_transaction(
    tx_input: TransactionInput,
    db: Session
) -> RiskResult:
    """
    Convenience function to evaluate a transaction.
    Creates engine and runs evaluation.
    """
    engine = ScoringEngine(db)
    return engine.evaluate_transaction(tx_input)
