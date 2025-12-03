"""
Pydantic schemas for request/response validation.
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, field_validator


class LocationInput(BaseModel):
    """Location coordinates."""
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lng: float = Field(..., ge=-180, le=180, description="Longitude")


class TransactionRequest(BaseModel):
    """Request schema for submitting a new transaction."""
    transaction_id: str = Field(..., min_length=1, max_length=100)
    user_id: str = Field(..., min_length=1, max_length=50)
    amount: float = Field(..., gt=0, description="Transaction amount (must be positive)")
    currency: str = Field(default="INR", min_length=3, max_length=10)
    merchant_id: str = Field(..., min_length=1, max_length=100)
    timestamp: datetime
    location: Optional[LocationInput] = None
    device_id: Optional[str] = Field(None, max_length=100)
    metadata: Optional[Dict[str, Any]] = None
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "transaction_id": "tx123",
                "user_id": "u100",
                "amount": 1250.50,
                "currency": "INR",
                "merchant_id": "m500",
                "timestamp": "2025-12-03T12:34:56Z",
                "location": {"lat": 12.9716, "lng": 77.5946},
                "device_id": "dev_1",
                "metadata": {"merchant_category": "travel", "channel": "nfc"}
            }
        }
    }


class TransactionResponse(BaseModel):
    """Response schema for transaction processing result."""
    transaction_id: str
    risk_score: int = Field(..., ge=0, le=100)
    risk_reasons: List[str]
    flagged: bool


class RiskDetailResponse(BaseModel):
    """Detailed risk evaluation response."""
    transaction_id: str
    user_id: str
    risk_score: int
    risk_reasons: List[str]
    raw_evidence: Dict[str, Any]
    evaluated_at: datetime
    flagged: bool


class FlaggedTransactionResponse(BaseModel):
    """Response for flagged transaction listing."""
    transaction_id: str
    user_id: str
    amount: float
    merchant_id: str
    risk_score: int
    risk_reasons: List[str]
    timestamp: datetime
    evaluated_at: datetime


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    database: Dict[str, Any]
    redis: Dict[str, Any]
    timestamp: datetime


class ErrorResponse(BaseModel):
    """Error response schema."""
    detail: str
    error_code: Optional[str] = None
