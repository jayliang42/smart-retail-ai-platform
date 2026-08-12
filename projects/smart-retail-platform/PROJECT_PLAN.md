# Project Delivery Plan

This is one evolving system, not four disconnected demos.

## 1. Retail Operations API

- [x] Store and SKU models
- [x] Inventory model and non-negative invariant
- [x] FastAPI create/query/adjust endpoints
- [ ] Learner-owned store read endpoint and explicit v1 update/delete policy
- [x] Idempotent inventory adjustments
- [x] In-memory unit/API test repository
- [x] PostgreSQL repository
- [x] Docker Compose runtime
- [x] Unit, API, and PostgreSQL integration tests
- [x] Alembic baseline migration and Docker migration gate
- [x] Device registration, lookup, and idempotent event ingestion
- [x] API-key authentication and role-based authorization for Copilot approvals
- [x] Authentication and actor audit trail for every direct operations write endpoint
- [ ] Cursor pagination and structured error envelopes
- [x] Concurrent first-write and idempotent-retry tests for inventory and pricing

## 2. Inventory Intelligence

- [x] Versioned store sales/inventory dataset
- [x] Data-quality checks and canonical parsing pipeline
- [x] Stockout and inventory anomaly baseline
- [x] Demand-forecasting baseline and time-aware validation
- [x] Baseline comparison and recorded metrics
- [x] Batch job plus prediction/anomaly API

## 3. Store Operations Copilot

- [x] SOP/manual ingestion with versioned sources
- [x] Retrieval and cited answers
- [x] Inventory, device, pricing, and ticket tools
- [x] Structured output and context management
- [x] Human approval for high-risk actions
- [x] Retry, timeout, permission, and recovery behavior

## 4. Production Hardening

- [x] 50–100 case evaluation dataset
- [x] Groundedness, citation, retrieval, tool, and approval-policy metrics
- [x] Regression evaluation in CI
- [x] Logging, request tracing, latency, token, and configurable cost telemetry
- [x] Bounded embedding cache, model routing, and transient fallback
- [x] CI workflow and provider-reviewed Render deployment blueprint
- [ ] Deploy to a user-authorized cloud account and run public smoke tests
- [x] Architecture diagram and 3–5 minute English demo
