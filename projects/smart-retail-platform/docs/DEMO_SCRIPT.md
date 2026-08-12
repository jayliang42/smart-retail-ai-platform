# 3–5 Minute English Demo Script

## 0:00–0:40 — Problem and product

“This is an AI-powered retail operations platform, not a prompt-only demo. It combines store,
inventory, pricing, work-order, and IoT data with analytics and a grounded operations Copilot. The
goal is to help an operator investigate an issue and take a controlled action without letting the
model bypass business rules.”

## 0:40–1:25 — Backend and data foundation

“FastAPI exposes the operational APIs. A repository interface has an in-memory implementation for
fast tests and a PostgreSQL implementation for the real runtime. Alembic owns the schema. Database
constraints enforce non-negative inventory and idempotency keys prevent duplicated adjustments or
events. The analytics batch validates the complete dataset before it stores an immutable run with
anomalies and walk-forward demand forecasts.”

## 1:25–2:15 — Grounded Copilot

“Operational manuals and SOPs are versioned, chunked, embedded, and stored in PostgreSQL with
pgvector. A Copilot answer must cite the exact retrieved chunk ID. If a model invents a citation or
claims a supported answer without evidence, the application rejects it. Local development uses a
deterministic lexical embedder and extractive fallback, so the system remains runnable without an
LLM key.”

## 2:15–3:10 — Tools and human approval

“The Agent has strict tools for inventory, devices, prices, and work orders. Read and low-risk tools
can execute directly. Inventory and price writes become persistent approval requests. The caller
cannot self-declare an approval role: the API resolves identity and role from an API key. A manager
can approve inventory changes, while a pricing lead can approve price changes. PostgreSQL row locks
prevent the same approval from executing twice.”

## 3:10–4:00 — Reliability and evaluation

“Model calls have a 20-second request timeout, bounded retries, a six-step Agent limit, and
structured tool errors. Every request receives a trace ID and JSON latency log. Agent telemetry
records provider attempts, tokens, tool calls, and an optional cost estimate. The versioned 60-case
regression suite measures retrieval recall and MRR, citation validity, tool behavior, and approval
policy. It currently passes all cases, but I explicitly treat this synthetic suite as contract
evidence, not production accuracy.”

## 4:00–4:35 — Deployment and next experiment

“GitHub Actions runs linting, type checks, migrations, unit and PostgreSQL tests, the Copilot
evaluation, and a container build. The non-root Docker image and Render blueprint are ready for an
authorized cloud account. My next experiment is to run the same workflow with a live model, add
human-reviewed multilingual cases, and record answer quality, p95 latency, and real token cost.”
