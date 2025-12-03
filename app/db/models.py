"""
SQLAlchemy ORM models for the fraud detection system.
Defines: users, transactions, risk_logs tables.
"""
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, DateTime, ForeignKey, 
    Integer, JSON, Text, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    """User model - stores basic user information."""
    __tablename__ = "users"
    
    user_id = Column(String(50), primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    transactions = relationship("Transaction", back_populates="user")
    risk_logs = relationship("RiskLog", back_populates="user")
    
    def __repr__(self):
        return f"<User(user_id={self.user_id})>"


class Transaction(Base):
    """Transaction model - stores financial transaction data."""
    __tablename__ = "transactions"
    
    transaction_id = Column(String(100), primary_key=True)
    user_id = Column(String(50), ForeignKey("users.user_id"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False, default="INR")
    merchant_id = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    location_lat = Column(Float, nullable=True)
    location_lng = Column(Float, nullable=True)
    device_id = Column(String(100), nullable=True)
    tx_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="transactions")
    risk_log = relationship("RiskLog", back_populates="transaction", uselist=False)
    
    # Indexes for common queries
    __table_args__ = (
        Index("idx_user_timestamp", "user_id", "timestamp"),
        Index("idx_user_merchant_amount", "user_id", "merchant_id", "amount"),
    )
    
    def __repr__(self):
        return f"<Transaction(id={self.transaction_id}, amount={self.amount})>"


class RiskLog(Base):
    """Risk log model - stores fraud risk evaluation results."""
    __tablename__ = "risk_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(
        String(100), 
        ForeignKey("transactions.transaction_id"), 
        nullable=False,
        unique=True,
        index=True
    )
    user_id = Column(String(50), ForeignKey("users.user_id"), nullable=False, index=True)
    risk_score = Column(Integer, nullable=False, index=True)
    reasons = Column(JSON, nullable=False, default=list)
    raw_evidence = Column(JSON, nullable=True)
    evaluated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    transaction = relationship("Transaction", back_populates="risk_log")
    user = relationship("User", back_populates="risk_logs")
    
    # Index for flagged transaction queries
    __table_args__ = (
        Index("idx_risk_score", "risk_score"),
    )
    
    def __repr__(self):
        return f"<RiskLog(tx={self.transaction_id}, score={self.risk_score})>"
