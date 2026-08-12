# AI Evaluations

The platform now has deterministic retrieval, citation, tool, and approval-policy evaluation in
addition to the traditional analytics baselines. Live LLM behavior has not been measured because
this runtime has no `OPENAI_API_KEY`; no live-model result is claimed below.

## Evaluation policy

Every AI capability must define, before release:

- a versioned input dataset;
- expected behavior or grading rubric;
- task-specific quality metrics;
- groundedness and failure checks where applicable;
- latency and cost measurements;
- regression thresholds and recorded experiment results.

## Experiment log

| Date | Feature | Dataset version | Model/config | Metrics | Result |
|---|---|---|---|---|---|
| 2026-08-11 | Inventory anomaly detection | `inventory_anomalies_v1` (30 cases, 11 positive) | Stockout only | Accuracy 0.7333; precision 1.0000; recall 0.2727; F1 0.4286 | Valid minimal baseline; misses most labeled risks |
| 2026-08-11 | Inventory anomaly detection | `inventory_anomalies_v1` (30 cases, 11 positive) | Prior-only inventory risk rules | Accuracy 1.0000; precision 1.0000; recall 1.0000; F1 1.0000 | Contract/regression sanity check passed |
| 2026-08-11 | One-step demand forecasting | `inventory_anomalies_v1` (24 walk-forward targets) | Last observed value after 3 history points | MAE 4.7500; RMSE 8.1240; WAPE 0.5278; mean bias 0.0000 | Minimal forecast baseline |
| 2026-08-11 | One-step demand forecasting | `inventory_anomalies_v1` (24 walk-forward targets) | Trailing mean, 7-day window, minimum 3 history points | MAE 3.2938; RMSE 6.4293; WAPE 0.3660; mean bias 0.2062 | Better than last-value on v1; not production evidence |
| 2026-08-11 | Knowledge retrieval | `copilot_eval_v1` (30 retrieval cases) | `sklearn_hashing_v1`, top-k 3 | Recall@3 1.0000; MRR 0.9778 | Deterministic lexical regression passed |
| 2026-08-11 | Citation contract | `copilot_eval_v1` (10 cases) | Retrieved/tool citation allowlist | Accuracy 1.0000 | Invented and contradictory citation states rejected |
| 2026-08-11 | Tool execution contract | `copilot_eval_v1` (10 cases) | Strict Pydantic schemas plus `ToolGateway` | Accuracy 1.0000 | Success, error, and approval-required paths matched labels |
| 2026-08-11 | Approval authorization policy | `copilot_eval_v1` (10 cases) | Server-side role policy | Accuracy 1.0000 | Manager/pricing-lead/admin boundaries matched labels |

## Interpretation limit

`inventory_anomalies_v1` is synthetic and hand-labeled using signals that closely match the richer
rule detector. Its perfect score proves that the implementation matches the current contract; it
does not estimate performance on real stores. Production-oriented evidence requires held-out data,
labels from incidents or human review, error analysis, and thresholds chosen independently of the
evaluation set.

Forecasts are generated before each target day's observation is appended to history. Both methods
use the same 24 target dates, avoiding an unfair comparison caused by different warm-up periods.

`copilot_eval_v1` is also synthetic and closely aligned with the checked-in English documents and
tool schemas. Its perfect component scores show that the regression harness, retrieval contract,
and safety rules behave as specified. They do not establish semantic retrieval quality on messy
enterprise documents, multilingual performance, live Agent task success, or production
groundedness.

`copilot_live_agent_v1` contains 12 additional end-to-end scenarios with expected tool/status
sequences, approval outcomes, and knowledge sections. The harness is implemented and tested with a
scripted model, but the dataset has **not** been executed against OpenAI. It therefore has no result
row in the experiment table.

## Required live-model experiment

Before claiming an LLM baseline:

1. configure a real API key and pin an evaluated model ID;
2. add at least 20 end-to-end questions with expected tool, arguments, approval state, answer rubric,
   and allowed citations;
3. run at least three repetitions for non-deterministic behavior;
4. record task success, groundedness, citation precision, tool/argument accuracy, p50/p95 latency,
   input/output tokens, and actual cost; and
5. review every failure instead of accepting only an aggregate score.
