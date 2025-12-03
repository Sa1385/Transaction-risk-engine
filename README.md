📌 Overview

The Transaction Risk & Fraud Detection Engine is a production-style backend system that evaluates financial transactions and assigns a fraud-risk score using multiple rule-based and probabilistic signals — similar to real-world systems used by fintech companies like CRED, Stripe, PayPal, Razorpay, and others.

This backend identifies suspicious activity based on:

Unusual spending behavior

Rapid repeated transactions

Geo-location anomalies

Device changes

Duplicate patterns

Merchant risk levels

Designed using FastAPI, PostgreSQL, Redis, SQLAlchemy, and Docker, this system demonstrates clean architecture, modular scoring, real-time evaluation, and scalable infrastructure.

🚀 Features
✔️ Real-time Fraud Scoring

Assigns a score (0–100) with detailed reasons and evidence.

✔️ Multiple Fraud Signals

Amount spike detection

Velocity spike detection (1 min & 10 min windows)

Location mismatch via Haversine formula

Device change monitoring

Merchant blacklist

Duplicate transaction patterns

✔️ Scalable Architecture

PostgreSQL for durable storage

Redis for caching & sliding windows

Clean modular code

Containerized with Docker

✔️ Production-Grade API

FastAPI with auto OpenAPI docs

Idempotent transaction submission

Strong request validation

✔️ Testing

PyTest test suite

Unit + integration tests

Scoring engine validation

🧠 How the Risk Engine Works

For each incoming transaction, the engine applies modular rules:

Signal	Description	Score
Amount Spike	Amount > 5× user’s average	+30
Velocity Spike	≥3 transactions in last 60s	+25
Velocity Unusual	≥5 transactions in 10 minutes	+15
Location Mismatch	>500 km jump within 12 hours	+20
Device Change	New or suspicious device ID	+10
Merchant Blacklist	High-risk merchants	+40
Duplicate Transaction	Same amount + merchant in 30s	+35

Final score is clamped between 0–100.

The engine stores:

risk score

reasons

raw evidence

timestamps

This simulates how real fintech risk engines work.

🏗️ System Architecture
flowchart TD

A[Client / App] --> B[FastAPI Backend]

B --> C1[Risk Scoring Engine]
B --> C2[PostgreSQL]
B --> C3[Redis Cache]

C1 --> C2
C1 --> C3

C1 --> D[Risk Score + Reasons Returned]

🛠️ Tech Stack
Layer	Technology
Backend	FastAPI (Python)
Database	PostgreSQL + SQLAlchemy ORM
Cache	Redis
Containerization	Docker + docker-compose
Testing	PyTest
Documentation	FastAPI OpenAPI UI
📦 Project Structure
transaction-risk-engine/
│
├── app/
│   ├── main.py
│   ├── api/
│   │   └── routes.py
│   ├── scoring/
│   │   └── engine.py
│   ├── db/
│   │   ├── models.py
│   │   └── session.py
│   ├── cache/
│   │   └── redis_client.py
│   └── tests/
│       ├── test_scoring.py
│       └── test_api.py
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── README.md
└── .gitignore

🐳 Run with Docker (Recommended)
docker-compose up --build


API available at:
👉 http://localhost:8000

Swagger docs:
👉 http://localhost:8000/docs

▶️ Run Locally (Without Docker)
pip install -r requirements.txt
uvicorn app.main:app --reload

🧪 Testing

Run the entire test suite:

pytest


Includes:

scoring rule tests

API endpoint tests

edge-case simulations

🔌 API Endpoints
POST /transactions

Submit a transaction for scoring.

{
  "transaction_id": "tx1",
  "user_id": "user_123",
  "amount": 9999.99,
  "currency": "INR",
  "merchant_id": "m_100",
  "timestamp": "2025-12-03T09:00:00Z",
  "location": {"lat": 19.07, "lng": 72.87},
  "device_id": "dev_x"
}

GET /risk/{transaction_id}

Fetch risk score + reasons.

GET /flags?min_score=70

Get all flagged high-risk transactions.

GET /health

Health check for DB + Redis.
