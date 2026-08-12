# Progress

## Current status

- Current week: 1
- Current session: Store Operations Copilot and production hardening
- Project status: All four local stages are implemented; external cloud and live-model validation await credentials
- Skill levels: Personal baseline still awaiting the learner's implementation/explanation

## Verified project evidence — 2026-08-11

- Project runtime: Python 3.13 virtual environment
- API: FastAPI endpoints for stores, SKUs, inventory, device registration, and device events
- Domain behavior: non-negative inventory and non-zero integer adjustments
- Reliability: request/event IDs make identical inventory and device-event retries idempotent
- Persistence: PostgreSQL implementation through SQLAlchemy/psycopg
- Local deployment: Docker Compose starts API plus PostgreSQL
- Schema evolution: Alembic baseline migration runs before the API starts
- Automated verification: 75 local tests passed; 9 PostgreSQL integration tests passed
- Quality gates: Ruff passed; basedpyright reported 0 errors and 0 warnings
- End-to-end verification: HTTP created store/SKU/inventory data; SQL confirmed quantity 12 and exactly one adjustment after a replay
- Migration verification: existing v0.1 data was preserved; a fresh PostgreSQL database migrated from zero; `alembic check` found no metadata drift
- Database invariant verification: PostgreSQL rejected a direct negative-inventory insert
- Device-event verification: HTTP replay produced one JSONB event row; event time, receipt time, type, status, and payload were preserved
- Migration chain: a fresh database upgraded through `0001 → 0002` and produced all 7 expected tables
- Data contract: versioned daily sales/inventory CSV with strict parsing, duplicate detection, non-negative quantities, and positive-price checks
- Inventory intelligence: stockout-only and prior-only explainable risk detectors implemented
- Analytics evaluation: on synthetic `inventory_anomalies_v1` (30 cases, 11 positive), stockout-only F1 was 0.4286 and risk-rules F1 was 1.0000
- Forecast evaluation: on 24 shared walk-forward targets, last-value MAE was 4.7500 and trailing-mean MAE was 3.2938; target-day demand was never included in its own prediction history
- Evaluation caveat: the richer rules closely match the hand-label rubric, so the perfect result is only contract/regression evidence
- Batch persistence: Alembic `0003` adds immutable run metadata, flagged anomaly results, and demand forecasts
- Analytics API: run metadata and bounded store/SKU anomaly/forecast queries verified through HTTP
- End-to-end analytics verification: `e2e-analytics-v1` persisted 11 anomalies and 24 forecasts to PostgreSQL and returned them from the running API
- Migration chain: a fresh temporary database upgraded through `0001 → 0002 → 0003`, produced 10 tables, and was removed
- Knowledge layer: three versioned sources and nine stable-citation chunks persisted with pgvector and HNSW cosine search
- Grounded Copilot: structured answers reject invented citations and unsupported evidence claims; deterministic fallback remains runnable without an API key
- Agent tools: inventory, device, price, and work-order tools use strict schemas and structured result/error envelopes
- Human control: Agent inventory/price writes persist pending approvals; API-key-derived manager/pricing-lead roles gate execution; database row locks prevent duplicate execution
- Agent reliability: 20-second provider request timeout, three bounded attempts, six Agent steps, eight tool calls per turn, and explicit unavailable/step-limit failures
- Copilot evaluation: all 60 `copilot_eval_v1` cases passed; retrieval Recall@3 1.0000 and MRR 0.9778; citation, tool, and policy accuracy 1.0000
- Observability: HTTP responses include request IDs; Docker logs contain JSON method/path/status/latency events; Agent results record tokens, attempts, tools, latency, and optional cost
- Trace correlation: one request ID is verified across HTTP completion, Agent completion, tool execution, retry, unavailable, and step-limit events
- Concurrency hardening: PostgreSQL advisory transaction locks protect first inventory/price writes and same-request concurrent retries; three race tests pass
- Live evaluation readiness: 12 end-to-end Agent cases and a scoring CLI cover tool/status sequences, approvals, required knowledge sections, latency, tokens, and cost; no live score is claimed without credentials
- Release path: GitHub Actions configuration covers static checks, migrations, all tests, Copilot evaluation, and Docker build
- Container hardening: rebuilt image runs as `uid=1000(appuser)` and serves PostgreSQL-backed `/health` successfully
- Direct-write security: store/SKU/device/event/inventory POST routes require API-key identity and role authorization
- Actor audit: successful direct writes persist actor, role, action, resource, request ID, and time in the same transaction; idempotent replay does not duplicate the event
- Auth/audit end-to-end: Docker returned 401 without a key, 201 for an admin store write, and the admin audit API plus PostgreSQL both exposed the matching `local-admin` event
- Migration chain: a fresh temporary database upgraded through `0001 → 0007`, produced 17 tables with the `vector` extension, and was removed
- Cloud preparation: Render blueprint uses managed PostgreSQL, private database networking, migration/knowledge pre-deploy gate, health checks, and dashboard-supplied secrets

## Current weak points / unknowns

- The implementation was AI-assisted, so the learner's independent Python, SQL, testing, and debugging levels remain unverified.
- Device event types still need explicit payload contracts and data-quality rules before analytics use them.
- Real/human-reviewed anomaly labels and stronger forecasting candidates have not started.
- Live OpenAI behavior has not been run because no API key is available; the 60-case result covers deterministic components, and the separate 12-case live suite remains unexecuted.
- The Render blueprint has not been deployed because no external cloud account/provider authorization was supplied.
- FastAPI's current test client emits an upstream deprecation warning; monitor rather than suppress it blindly.

## Next checkpoint

Complete the learner task in `sessions/2026-08-11.md`: implement the reserved store read endpoint and explain one Copilot request from retrieval through citation validation or tool approval. This remains necessary because generated project code is portfolio infrastructure, not evidence that the learner can independently debug and defend it.
