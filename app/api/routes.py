"""
API route definitions for the fraud detection service.
"""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db, check_db_health
from app.db.models import User, Transaction, RiskLog
from app.cache.redis_client import redis_client
from app.scoring.engine import evaluate_transaction, TransactionInput
from app.schemas import (
    TransactionRequest, TransactionResponse,
    RiskDetailResponse, FlaggedTransactionResponse,
    HealthResponse, ErrorResponse
)
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/transactions",
    response_model=TransactionResponse,
    responses={
        400: {"model": ErrorResponse},
        500: {"model": ErrorResponse}
    },
    summary="Process a new transaction",
    description="Submit a financial transaction for fraud risk evaluation"
)
def process_transaction(
    request: TransactionRequest,
    db: Session = Depends(get_db)
):
    """
    Process a new transaction and evaluate fraud risk.
    
    - Creates user if not exists
    - Stores transaction
    - Runs fraud scoring engine
    - Stores risk log
    - Updates Redis cache
    """
    try:
        # Check if transaction already exists (idempotency)
        existing_log = db.query(RiskLog).filter(
            RiskLog.transaction_id == request.transaction_id
        ).first()
        
        if existing_log:
            # Return existing result for idempotency
            return TransactionResponse(
                transaction_id=existing_log.transaction_id,
                risk_score=existing_log.risk_score,
                risk_reasons=existing_log.reasons,
                flagged=existing_log.risk_score >= settings.FLAG_THRESHOLD
            )
        
        # Create or get user
        user = db.query(User).filter(User.user_id == request.user_id).first()
        if not user:
            user = User(user_id=request.user_id)
            db.add(user)
            db.flush()
        
        # Create transaction record
        transaction = Transaction(
            transaction_id=request.transaction_id,
            user_id=request.user_id,
            amount=request.amount,
            currency=request.currency,
            merchant_id=request.merchant_id,
            timestamp=request.timestamp,
            location_lat=request.location.lat if request.location else None,
            location_lng=request.location.lng if request.location else None,
            device_id=request.device_id,
            tx_metadata=request.metadata
        )
        db.add(transaction)
        db.flush()
        
        # Build transaction input for scoring
        tx_input = TransactionInput(
            transaction_id=request.transaction_id,
            user_id=request.user_id,
            amount=request.amount,
            currency=request.currency,
            merchant_id=request.merchant_id,
            timestamp=request.timestamp,
            location_lat=request.location.lat if request.location else None,
            location_lng=request.location.lng if request.location else None,
            device_id=request.device_id,
            metadata=request.metadata
        )
        
        # Evaluate fraud risk
        risk_result = evaluate_transaction(tx_input, db)
        
        # Store risk log
        risk_log = RiskLog(
            transaction_id=request.transaction_id,
            user_id=request.user_id,
            risk_score=risk_result.score,
            reasons=risk_result.reasons,
            raw_evidence=risk_result.evidence,
            evaluated_at=datetime.utcnow()
        )
        db.add(risk_log)
        
        # Commit all changes
        db.commit()
        
        # Update Redis cache (after successful commit)
        try:
            # Update last known device/location
            if request.device_id or request.location:
                redis_client.set_last_known(
                    user_id=request.user_id,
                    device_id=request.device_id or "",
                    lat=request.location.lat if request.location else None,
                    lng=request.location.lng if request.location else None,
                    timestamp=request.timestamp
                )
            
            # Add to recent transactions
            redis_client.add_recent_transaction(
                user_id=request.user_id,
                timestamp=request.timestamp,
                tx_id=request.transaction_id
            )
        except Exception as cache_error:
            # Log but don't fail the request for cache errors
            logger.warning(f"Cache update failed: {cache_error}")
        
        return TransactionResponse(
            transaction_id=request.transaction_id,
            risk_score=risk_result.score,
            risk_reasons=risk_result.reasons,
            flagged=risk_result.flagged
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error processing transaction: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/risk/{transaction_id}",
    response_model=RiskDetailResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get risk evaluation for a transaction",
    description="Retrieve the stored risk evaluation result for a specific transaction"
)
def get_risk(
    transaction_id: str,
    db: Session = Depends(get_db)
):
    """Get stored risk evaluation for a transaction."""
    risk_log = db.query(RiskLog).filter(
        RiskLog.transaction_id == transaction_id
    ).first()
    
    if not risk_log:
        raise HTTPException(
            status_code=404,
            detail=f"Risk evaluation not found for transaction: {transaction_id}"
        )
    
    return RiskDetailResponse(
        transaction_id=risk_log.transaction_id,
        user_id=risk_log.user_id,
        risk_score=risk_log.risk_score,
        risk_reasons=risk_log.reasons,
        raw_evidence=risk_log.raw_evidence,
        evaluated_at=risk_log.evaluated_at,
        flagged=risk_log.risk_score >= settings.FLAG_THRESHOLD
    )


@router.get(
    "/flags",
    response_model=List[FlaggedTransactionResponse],
    summary="List flagged transactions",
    description="Retrieve a list of transactions with risk scores above the threshold"
)
def get_flagged_transactions(
    min_score: int = Query(default=50, ge=0, le=100, description="Minimum risk score"),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of results"),
    db: Session = Depends(get_db)
):
    """
    Get list of flagged transactions.
    Filters by minimum score and limits results.
    """
    results = db.query(RiskLog, Transaction).join(
        Transaction, RiskLog.transaction_id == Transaction.transaction_id
    ).filter(
        RiskLog.risk_score >= min_score
    ).order_by(
        RiskLog.risk_score.desc(),
        RiskLog.evaluated_at.desc()
    ).limit(limit).all()
    
    return [
        FlaggedTransactionResponse(
            transaction_id=risk_log.transaction_id,
            user_id=risk_log.user_id,
            amount=transaction.amount,
            merchant_id=transaction.merchant_id,
            risk_score=risk_log.risk_score,
            risk_reasons=risk_log.reasons,
            timestamp=transaction.timestamp,
            evaluated_at=risk_log.evaluated_at
        )
        for risk_log, transaction in results
    ]


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Check the health status of the service, database, and Redis"
)
def health_check():
    """
    Health check endpoint.
    Returns status of database and Redis connections.
    """
    db_health = check_db_health()
    redis_health = redis_client.health_check()
    
    overall_status = "healthy"
    if db_health["status"] != "healthy" or redis_health["status"] != "healthy":
        overall_status = "degraded"
    
    return HealthResponse(
        status=overall_status,
        database=db_health,
        redis=redis_health,
        timestamp=datetime.utcnow()
    )
