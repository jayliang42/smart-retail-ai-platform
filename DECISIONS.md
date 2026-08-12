# Architecture Decision Log

## ADR-001: Build one evolving vertical product

- Status: Accepted
- Decision: Use one repository and one continuously evolving Smart Retail Operations Platform rather than disconnected exercises.
- Reason: Each learning artifact becomes portfolio evidence and later features exercise integration tradeoffs.

## ADR-002: Start with domain behavior before frameworks

- Status: Accepted
- Decision: The first coding baseline uses Python domain logic and tests before FastAPI, PostgreSQL, or LLM dependencies.
- Reason: This isolates core Python reasoning and prevents framework setup from hiding skill gaps.

## ADR-003: Project Python and dependency workflow

- Status: Accepted
- Decision: Use Python 3.13 for the project and a local `.venv`; declare support for Python 3.12–3.13.
- Reason: The host default is Python 3.14, while Python 3.13 provides a conservative compatibility target for the backend/data/AI dependency stack and matches the Docker image.

## ADR-004: Repository boundary with two implementations

- Status: Accepted
- Decision: Define a small `RetailRepository` protocol with an in-memory implementation for fast tests and a PostgreSQL implementation for the real runtime.
- Reason: Domain/API tests remain deterministic while production-path behavior can be integration-tested independently.
- Tradeoff: Both implementations must pass the same behavioral contract; contract tests will be strengthened as operations grow.

## ADR-005: Idempotent inventory adjustments

- Status: Accepted
- Decision: Require a caller-supplied `request_id`. Replaying the same payload returns the original result; reusing the ID with a different payload returns HTTP 409.
- Reason: Clients and gateways retry requests. Without idempotency, a retry could apply the same delivery or sale twice.

## ADR-006: Temporary schema bootstrap

- Status: Superseded by ADR-008
- Decision: Use SQLAlchemy `metadata.create_all()` for v0.1 local startup.
- Reason: It keeps the first vertical slice runnable while the schema is still small.
- Outcome: Replaced with Alembic before v0.2.

## ADR-007: Synchronous database path for v0.1

- Status: Accepted
- Decision: Use synchronous SQLAlchemy sessions and ordinary FastAPI handlers for the first slice.
- Reason: It reduces operational complexity while learning transactions and repository behavior. Async I/O will be adopted only when measured concurrency needs justify it.

## ADR-008: Alembic owns database schema evolution

- Status: Accepted
- Decision: Remove runtime `create_all()` and apply versioned Alembic migrations through a one-shot Docker `migrate` service. The API starts only after migration success.
- Reason: Deployments need reviewable, repeatable upgrades and an explicit schema version; silently creating missing tables cannot safely evolve existing columns or data.
- Compatibility: The baseline migration recognizes the pre-Alembic v0.1 schema, preserves existing data, and adds the missing database constraints and version record.
- Defense in depth: PostgreSQL check constraints reject negative inventory, zero deltas, and negative adjustment results even if a future code path bypasses domain validation.

## ADR-009: Store raw device events as idempotent observations

- Status: Accepted
- Decision: Register devices explicitly, store event payloads as PostgreSQL JSONB, and require a globally unique caller-supplied `event_id`.
- Time semantics: Preserve both `observed_at` from the device and `received_at` from the platform. Forecasting and anomaly detection need event time, while operational latency and late-arrival analysis need receipt time.
- Retry behavior: Replaying the same event returns the original record; reusing an `event_id` with a different payload returns HTTP 409.
- Tradeoff: JSONB supports multiple device types without premature table proliferation, but event-type-specific schemas and data-quality validation must be added before analytics consume these payloads.

## ADR-010: Establish a versioned, time-aware analytics baseline before ML

- Status: Accepted
- Decision: Keep evaluation inputs versioned in the repository, validate them against an explicit daily retail data contract, and compare a minimal stockout-only detector with richer explainable inventory-risk rules.
- Time semantics: Rolling demand for a business date may use only earlier observations for the same store and SKU. Using the current or future label period would leak information and inflate offline metrics.
- Reason: A simple baseline reveals whether added complexity produces measurable value, while named reasons such as `low_stock_coverage` and `demand_spike` make errors reviewable by operators.
- Limitation: The first dataset is small, synthetic, and labeled from nearly the same rule rubric. Its perfect rule score is a pipeline sanity check, not production performance evidence.

## ADR-011: Persist immutable analytics runs before serving results

- Status: Accepted
- Decision: A batch run has a unique `run_id` and records its dataset version, input count, anomaly detector, forecaster, and creation time. Forecasts and flagged anomalies are stored under that run rather than overwritten as a single “latest” result.
- Reason: Operators and evaluators need to reproduce which configuration created a result; mutable latest-only tables lose lineage and make regressions hard to explain.
- API behavior: Result endpoints require a run ID and support bounded store/SKU filters. The batch path validates the complete dataset before opening a persistence operation.
- Tradeoff: The current tables retain observed demand for offline comparison and do not yet separate backtest outputs from future production forecasts. That distinction must be explicit before real-time use.

## ADR-012: Keep knowledge sources versioned and citations stable

- Status: Accepted
- Decision: Ingest manifest-declared Markdown sources as immutable source versions, split them deterministically by section and paragraph, and derive stable chunk IDs from source identity and content.
- Storage: Keep metadata and 256-dimensional vectors in PostgreSQL with pgvector and an HNSW cosine index.
- Reason: An operational answer needs a durable evidence pointer that can be reproduced after a deployment or document update.
- Limitation: The local hashing embedder is lexical and deterministic. It is useful for tests and offline development, not evidence of production semantic retrieval.

## ADR-013: Validate model output against an evidence allowlist

- Status: Accepted
- Decision: Parse answers into strict structured output and accept only citation IDs present in that run's retrieved chunks or tool results.
- Failure behavior: Reject invented citations, supported answers with no citations, and insufficient-evidence answers that still claim citations.
- Reason: Prompt instructions alone do not enforce groundedness. The application must verify the claim after generation.

## ADR-014: Put a risk-aware gateway between the Agent and business writes

- Status: Accepted
- Decision: Give the model strict inventory, device, price, and work-order tools. Read and low-risk work-order calls execute directly; inventory and price writes create persistent approval requests.
- Authorization: Resolve approver identity and role from an opaque API key. Managers approve inventory changes; pricing leads approve price changes; admins can approve either.
- Concurrency: Claim approved work under a PostgreSQL row lock before execution so that concurrent decisions cannot execute the same action twice.
- Tradeoff: The portfolio API-key boundary must later be replaced by managed enterprise identity, rotation, scopes, and complete actor auditing.

## ADR-015: Bound every Agent failure mode

- Status: Accepted
- Decision: Use a 20-second provider timeout, three total attempts with bounded delay, a six-step Agent limit, strict tool errors, and a maximum of eight tool calls per model turn.
- Fallback: For cited question answering, transient provider failures may fall back to deterministic extraction. Protocol, parsing, and grounding violations remain visible errors.
- Reason: An autonomous loop must have an explicit stopping condition and must not hide integrity failures as successful fallbacks.

## ADR-016: Treat evaluation and telemetry as release gates

- Status: Accepted
- Decision: Version the 60-case deterministic Copilot suite and run it with unit tests, PostgreSQL integration tests, migration drift checks, static checks, and container builds in CI.
- Telemetry: Emit request IDs and JSON latency logs; record Agent attempts, tokens, tool count, latency, and cost only when deployment-specific rates are configured.
- Limitation: The deterministic suite is contract evidence. A live-model, human-reviewed evaluation remains required before claiming LLM quality.

## ADR-017: Serialize first writes with transaction-scoped advisory locks

- Status: Accepted
- Problem: `SELECT ... FOR UPDATE` protects an existing inventory or price row, but it cannot lock a row that does not exist during the first concurrent write.
- Decision: Acquire a PostgreSQL transaction-scoped advisory lock derived from the store/SKU operation key before checking idempotency and reading or creating the row.
- Evidence: Concurrent integration tests cover two distinct first inventory adjustments, two simultaneous replays of one request ID, and two distinct first price changes.
- Tradeoff: A hash collision can serialize unrelated keys but cannot corrupt data. Advisory locks are PostgreSQL-specific, which is consistent with the chosen production datastore.

## ADR-018: Separate deterministic CI evaluation from live-model evaluation

- Status: Accepted
- Decision: Keep the 60-case deterministic suite as a mandatory CI gate and maintain a separate 12-case live Agent suite that requires an explicit API key.
- Reason: CI must be reproducible and free from provider variability, while model selection still needs end-to-end evidence for tool choice, approval behavior, citations, latency, tokens, and cost.
- Integrity rule: Missing credentials produce no score. A scripted-model harness test proves evaluator mechanics but is never reported as live-model quality.

## ADR-019: Authenticate and audit direct operations writes atomically

- Status: Accepted
- Decision: Resolve API-key identity before every direct store, SKU, device, device-event, and inventory write; authorize the operation from the server-side role; persist the actor audit event in the same database transaction as the mutation.
- Roles: Catalog writes require `admin`; device registration accepts `manager` or `admin`; device-event and inventory writes accept `operator`, `manager`, or `admin`; audit queries require `admin`.
- Retry behavior: An idempotent replay returns the original business result and does not create another audit event.
- Reason: A successful business write without its audit record, or an audit record for a rolled-back write, would produce an unreliable evidence trail. One transaction preserves the invariant.
- Tradeoff: Static API keys are adequate for a controlled portfolio deployment, but production still needs managed identity, rotation, scoped service accounts, and an external append-only sink.
