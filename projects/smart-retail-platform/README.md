# AI-Powered Smart Retail Operations Platform

An evolving portfolio project for ingesting retail and IoT events, serving operational data,
detecting anomalies, forecasting demand, and providing a grounded, controlled Store Operations
Copilot.

## Current milestone: production-oriented Copilot release candidate

The evolving vertical product now supports:

- store and SKU creation;
- inventory lookup;
- non-negative inventory adjustments;
- idempotent adjustment requests;
- device registration and lookup;
- idempotent device-event ingestion with observed and received timestamps;
- bounded per-device event queries;
- an in-memory repository for fast tests;
- a PostgreSQL repository for the Docker runtime;
- FastAPI/OpenAPI endpoints and automated tests.
- versioned analytics inputs and immutable batch runs;
- a versioned daily sales/inventory CSV contract;
- canonical parsing and explicit data-quality reports;
- a minimal stockout-only detector;
- an explainable inventory-risk detector using only prior observations; and
- last-value and trailing-mean demand forecasts evaluated with walk-forward validation;
- versioned SOP/manual ingestion into PostgreSQL and pgvector;
- cited retrieval and structured Copilot answers;
- typed inventory, device, pricing, and work-order tools;
- persistent human approval for high-risk Agent writes;
- API-key-derived approver identities and role policies;
- role-protected direct operations writes with transactionally persisted actor audit events;
- bounded model retries, timeout, Agent steps, cache, and transient fallback;
- JSON request tracing plus Agent token, latency, tool, and optional cost telemetry; and
- a 60-case deterministic Copilot regression suite in CI.

See [the architecture](docs/ARCHITECTURE.md), [English demo script](docs/DEMO_SCRIPT.md), and
[delivery checklist](PROJECT_PLAN.md).

## Evaluate the inventory anomaly baselines

Run the evaluation from the project root:

```bash
PYTHONPATH=src .venv/bin/python -m smart_retail.analytics.cli \
  data/evaluation/inventory_anomalies_v1.csv
```

The checked-in `inventory_anomalies_v1` dataset is a small synthetic, hand-labeled contract and
regression dataset. It verifies data validation, time ordering, detector behavior, and metric
calculation. Its perfect score for the richer rule set is **not** evidence of production accuracy;
the labels closely follow the documented rules. A later evaluation version will use held-out,
human-reviewed operational cases.

The same command evaluates one-step demand forecasts on 24 comparable target dates. In v1, the
last-value baseline has MAE `4.75` and the trailing-mean baseline has MAE `3.29`. This comparison
validates the no-future-data evaluation path; the sample is too small and synthetic to select a
production forecasting method.

## Persist a batch and query results

Start PostgreSQL and the API so that Alembic applies the analytics schema:

```bash
docker compose up --build --detach
```

Then run the validated batch against PostgreSQL:

```bash
DATABASE_URL='postgresql+psycopg://smart_retail:local-development-only@localhost:5432/smart_retail' \
PYTHONPATH=src .venv/bin/python -m smart_retail.analytics.batch \
  data/evaluation/inventory_anomalies_v1.csv --run-id local-analytics-v1
```

The run ID binds the dataset version, detector configuration, forecaster configuration, and output
rows. Results can be filtered and bounded through:

```text
GET /analytics/runs/{run_id}
GET /analytics/runs/{run_id}/anomalies?store_id=...&sku=...&limit=...
GET /analytics/runs/{run_id}/forecasts?store_id=...&sku=...&limit=...
```

The anomaly result table stores only flagged cases; the forecast table stores all target dates after
the warm-up period.

## Ingest knowledge and run the Copilot

With PostgreSQL running, ingest the versioned manifest. Replaying an unchanged source is safe.

```bash
DATABASE_URL='postgresql+psycopg://smart_retail:local-development-only@localhost:5432/smart_retail' \
PYTHONPATH=src .venv/bin/python -m smart_retail.knowledge.ingestion \
  data/knowledge/manifest.json
```

Search and ask for a cited answer:

```bash
curl -X POST http://localhost:8000/knowledge/search \
  -H 'content-type: application/json' \
  -d '{"query":"verified dairy temperature above 5 degrees","limit":3}'

curl -X POST http://localhost:8000/copilot/ask \
  -H 'content-type: application/json' \
  -d '{"question":"What should I do after a verified 15-minute high-temperature alarm?"}'
```

Without `OPENAI_API_KEY`, `/copilot/ask` uses the deterministic extractive fallback and the
multi-step `/copilot/agent` endpoint returns 503. With a key, the application uses the OpenAI
Responses API with strict structured output and function schemas. Set `OPENAI_MODEL` to route to a
different evaluated model.

## Evaluate the Copilot contracts

```bash
PYTHONPATH=src .venv/bin/python -m smart_retail.copilot.evaluation \
  data/evaluation/copilot_eval_v1.jsonl data/knowledge/manifest.json
```

`copilot_eval_v1` has 60 cases: 30 retrieval cases, 10 citation/grounding cases, 10 tool-contract
cases, and 10 approval-policy cases. The checked-in baseline has Recall@3 `1.0`, MRR `0.9778`, and
accuracy `1.0` for the other three categories. This is a small synthetic English regression set;
it does not measure live-model answer quality or real-store performance.

An additional 12-case end-to-end suite is ready for an explicitly configured live model:

```bash
PYTHONPATH=src .venv/bin/python -m smart_retail.copilot.live_evaluation \
  data/evaluation/copilot_live_agent_v1.jsonl data/knowledge/manifest.json
```

It measures exact tool/status sequences, approval behavior, required knowledge sections, tokens,
latency, and optional cost. The command fails fast without `OPENAI_API_KEY`; there is no checked-in
live score yet.

## Approve a high-risk Agent action

Configure opaque keys as a JSON mapping. Identities and roles come from the server configuration,
not from request bodies.

```bash
export SMART_RETAIL_API_KEYS='{
  "replace-with-random-operator-key":{"actor_id":"operator-1","role":"operator"},
  "replace-with-random-pricing-key":{"actor_id":"pricing-lead-1","role":"pricing_lead"},
  "replace-with-random-admin-key":{"actor_id":"admin-1","role":"admin"}
}'
```

The authenticated Agent may create a pending request. A pricing lead can then execute an approved
price change:

```bash
curl -X POST http://localhost:8000/approvals/APPROVAL_ID/decision \
  -H 'content-type: application/json' \
  -H 'X-API-Key: replace-with-random-pricing-key' \
  -d '{"approved":true}'
```

Direct operations writes also require a configured key. Catalog writes require `admin`; device
registration accepts `manager` or `admin`; device-event and inventory writes accept `operator`,
`manager`, or `admin`. The write and its actor audit event commit in the same database transaction,
and only `admin` can query `GET /audit-events`.

Do not commit real API keys. The current API-key boundary is suitable for a portfolio deployment;
a production enterprise deployment should integrate a managed identity provider, key rotation,
scoped service accounts, and an external append-only audit sink.

## Observability and cost configuration

Every HTTP response carries `X-Request-ID`. Logs include a JSON event with method, path, status, and
latency. Agent responses include provider attempts, input/output tokens, tool calls, latency, and an
optional cost estimate. Cost is only computed when both deployment-specific rates are configured:

```bash
export OPENAI_INPUT_COST_PER_MILLION_USD='replace-with-current-rate'
export OPENAI_OUTPUT_COST_PER_MILLION_USD='replace-with-current-rate'
```

Rates are intentionally not hardcoded because model pricing can change.

## Run locally

Use Python 3.12 or 3.13. The host's default Python may be newer than the supported project
runtime.

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/uvicorn --app-dir src smart_retail.api.app:app --reload
```

Without `DATABASE_URL`, the API uses the in-memory repository. Open
`http://localhost:8000/docs` to explore the API.

## Run with PostgreSQL

```bash
export SMART_RETAIL_API_KEYS='{
  "local-admin-key":{"actor_id":"local-admin","role":"admin"}
}'
docker compose up --build
```

The API is available at `http://localhost:8000`; PostgreSQL is exposed on port `5432` for
local inspection. Docker runs the one-shot `migrate` service first and starts the API only after
`alembic upgrade head` succeeds.

The application image runs as the non-root `appuser` user. The database image includes pgvector.

Run the PostgreSQL integration test while the database container is running:

```bash
TEST_DATABASE_URL='postgresql+psycopg://smart_retail:local-development-only@localhost:5432/smart_retail' \
  .venv/bin/pytest tests/test_postgres_repository.py
```

## Database migrations

Alembic is the only owner of schema changes. Do not add `metadata.create_all()` to application
startup.

```bash
DATABASE_URL='postgresql+psycopg://smart_retail:local-development-only@localhost:5432/smart_retail' \
  .venv/bin/alembic upgrade head

DATABASE_URL='postgresql+psycopg://smart_retail:local-development-only@localhost:5432/smart_retail' \
  .venv/bin/alembic check
```

Create a new migration after changing SQLAlchemy metadata:

```bash
DATABASE_URL='postgresql+psycopg://smart_retail:local-development-only@localhost:5432/smart_retail' \
  .venv/bin/alembic revision --autogenerate -m 'describe the schema change'
```

Review generated migrations before applying them; autogeneration cannot infer every data-migration
or deployment-safety requirement.

## CI and cloud release

`.github/workflows/ci.yml` runs Ruff, basedpyright, the full test suite against pgvector PostgreSQL,
`alembic check`, the 60-case Copilot regression suite, and an OCI image build.

`render.yaml` defines a Docker web service plus managed PostgreSQL. Its pre-deploy command applies
migrations and idempotently ingests the checked-in knowledge manifest. `OPENAI_API_KEY` and
`SMART_RETAIL_API_KEYS` are dashboard-provided secrets. Creating the external resources is
intentionally left to an authorized cloud account owner.

## Example flow

```bash
curl -X POST http://localhost:8000/stores \
  -H 'content-type: application/json' \
  -H 'X-API-Key: local-admin-key' \
  -d '{"store_id":"store-1","name":"Chicago Loop"}'

curl -X POST http://localhost:8000/skus \
  -H 'content-type: application/json' \
  -H 'X-API-Key: local-admin-key' \
  -d '{"sku":"sku-1","name":"Milk"}'

curl -X POST http://localhost:8000/inventory/adjustments \
  -H 'content-type: application/json' \
  -H 'X-API-Key: local-admin-key' \
  -d '{"request_id":"delivery-1","store_id":"store-1","sku":"sku-1","quantity_delta":12,"reason":"morning delivery"}'

curl -X POST http://localhost:8000/devices \
  -H 'content-type: application/json' \
  -H 'X-API-Key: local-admin-key' \
  -d '{"device_id":"sensor-1","store_id":"store-1","device_type":"temperature_sensor","display_name":"Dairy sensor"}'

curl -X POST http://localhost:8000/device-events \
  -H 'content-type: application/json' \
  -H 'X-API-Key: local-admin-key' \
  -d '{"event_id":"event-1","device_id":"sensor-1","event_type":"temperature_reading","observed_at":"2026-08-11T10:00:00Z","payload":{"temperature_c":3.2}}'

curl 'http://localhost:8000/audit-events?resource_type=inventory' \
  -H 'X-API-Key: local-admin-key'
```

## Planned evolution

1. Add cursor pagination and structured error envelopes to the operations API.
2. Replace synthetic analytics labels with independently reviewed operational incidents and compare
   stronger forecasting candidates.
3. Run live-model evaluation with human-reviewed English and Chinese cases; record groundedness,
   task success, p95 latency, and real cost.
4. Deploy the checked-in blueprint to an authorized account and run public migration, health,
   retrieval, authentication, and approval smoke tests.
