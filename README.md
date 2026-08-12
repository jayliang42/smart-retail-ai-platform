# Smart Retail AI Engineering Portfolio

This private learning repository tracks one evolving, production-oriented system rather than four
unrelated demos: the **AI-Powered Smart Retail Operations Platform**.

| Stage | Evidence | Status |
|---|---|---|
| Retail Operations API | FastAPI, PostgreSQL, migrations, tests, Docker, role-based writes, audit trail | Locally verified; one learner-owned endpoint remains |
| Inventory Intelligence | Data-quality pipeline, anomaly baselines, demand forecasting, batch results API | Locally verified on synthetic v1 data |
| Store Operations Copilot | Versioned RAG, citations, typed tools, approvals, bounded Agent workflow | Deterministic evaluation verified; live LLM evaluation pending |
| Production Hardening | 60-case regression suite, tracing, cost/latency telemetry, CI, deployment blueprint | Local gates verified; cloud deployment pending |

Start with the [project README](projects/smart-retail-platform/README.md) and the
[completion audit](projects/smart-retail-platform/COMPLETION_AUDIT.md).

## Repository map

- `projects/smart-retail-platform/`: runnable application, tests, data, migrations, and deployment configuration
- `ROADMAP.md`: 24-week learning roadmap
- `PROFILE.md`: current evidence-based skill profile
- `PROGRESS.md`: verified progress and current weak points
- `DECISIONS.md`: architecture decision records
- `AI_EVALUATIONS.md`: datasets, metrics, results, and evaluation limits
- `sessions/`: daily learner tasks and session notes

## Current verification

From `projects/smart-retail-platform/`:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/basedpyright
```

The project intentionally distinguishes deterministic component evaluation from live-model
evidence. No live LLM quality or cloud deployment result is claimed until the corresponding
credentials and external account are explicitly configured.
