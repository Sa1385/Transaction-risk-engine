-- Initialize database tables for Transaction Risk & Fraud Detection Engine
-- This script runs automatically when PostgreSQL container starts

-- Create users table
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(50) PRIMARY KEY,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create transactions table
-- Renamed 'metadata' column to 'tx_metadata' to avoid SQLAlchemy reserved word conflict
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id VARCHAR(100) PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL REFERENCES users(user_id),
    amount FLOAT NOT NULL,
    currency VARCHAR(10) NOT NULL DEFAULT 'INR',
    merchant_id VARCHAR(100) NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    location_lat FLOAT,
    location_lng FLOAT,
    device_id VARCHAR(100),
    tx_metadata JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create risk_logs table
CREATE TABLE IF NOT EXISTS risk_logs (
    id SERIAL PRIMARY KEY,
    transaction_id VARCHAR(100) NOT NULL UNIQUE REFERENCES transactions(transaction_id),
    user_id VARCHAR(50) NOT NULL REFERENCES users(user_id),
    risk_score INTEGER NOT NULL,
    reasons JSONB NOT NULL DEFAULT '[]',
    raw_evidence JSONB,
    evaluated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_transactions_merchant_id ON transactions(merchant_id);
CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(timestamp);
CREATE INDEX IF NOT EXISTS idx_transactions_user_timestamp ON transactions(user_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_transactions_user_merchant_amount ON transactions(user_id, merchant_id, amount);
CREATE INDEX IF NOT EXISTS idx_risk_logs_transaction_id ON risk_logs(transaction_id);
CREATE INDEX IF NOT EXISTS idx_risk_logs_user_id ON risk_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_risk_logs_risk_score ON risk_logs(risk_score);

-- Insert some test data
INSERT INTO users (user_id) VALUES 
    ('u100'),
    ('u101'),
    ('u102')
ON CONFLICT DO NOTHING;

-- Sample transactions for testing (30 day history for u100)
-- Updated to use 'tx_metadata' column name
INSERT INTO transactions (transaction_id, user_id, amount, currency, merchant_id, timestamp, location_lat, location_lng, device_id, tx_metadata)
SELECT 
    'hist_' || generate_series || '_' || md5(random()::text),
    'u100',
    (random() * 200 + 50)::numeric(10,2),
    'INR',
    'm_normal_' || (random() * 5 + 1)::int,
    NOW() - (generate_series || ' days')::interval,
    12.9716 + (random() - 0.5) * 0.1,
    77.5946 + (random() - 0.5) * 0.1,
    'dev_1',
    '{"channel": "web"}'::jsonb
FROM generate_series(1, 20)
ON CONFLICT DO NOTHING;

COMMENT ON TABLE users IS 'User accounts for fraud detection';
COMMENT ON TABLE transactions IS 'Financial transaction records';
COMMENT ON TABLE risk_logs IS 'Fraud risk evaluation results';
