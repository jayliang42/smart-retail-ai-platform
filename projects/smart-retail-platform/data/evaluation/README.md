# Evaluation datasets

## `inventory_anomalies_v1.csv`

Purpose: verify the daily retail data contract, anomaly detector behavior, and evaluation pipeline.
This is a synthetic contract/regression dataset, not a representative sample of production stores.

Each row represents one store/SKU business day:

| Column | Contract |
|---|---|
| `business_date` | ISO calendar date |
| `store_id` | Non-empty store identifier |
| `sku` | Non-empty SKU identifier |
| `units_sold` | Non-negative integer |
| `ending_inventory` | Non-negative integer |
| `unit_price` | Positive decimal |
| `expected_anomaly` | Optional boolean label used only for evaluation |

The v1 labels cover three operator-readable signals after at least three prior observations:

- stockout while recent demand exists;
- ending inventory at or below roughly one trailing-demand day; and
- current demand above twice the trailing mean.

The production detector must calculate trailing demand from earlier dates only. The current labels
closely mirror these rules, so a perfect rules-based score confirms implementation consistency but
does not demonstrate generalization. A stronger future dataset must contain held-out records labeled
from real incidents or independent human review, followed by false-positive and false-negative error
analysis.

The same daily observations support one-step forecast regression tests. Forecasts begin only after
three prior observations, and all forecasters are scored on the same target dates using MAE, RMSE,
WAPE, and mean bias. The target day's `units_sold` is appended to history only after its prediction
has been created.

## `copilot_eval_v1.jsonl`

Purpose: provide 60 deterministic, offline regression cases for the Copilot's supporting contracts:

- 30 knowledge-retrieval cases scored with Recall@3 and MRR;
- 10 citation/grounding state cases;
- 10 typed tool execution cases; and
- 10 approval-role policy cases.

These cases are intentionally runnable without a model API key. They prove contract behavior and
make CI failures reproducible, but they do not estimate live-model quality.

## `copilot_live_agent_v1.jsonl`

Purpose: provide 12 optional end-to-end Agent cases for an explicitly configured live model. Cases
cover successful and missing inventory/device/price reads, work-order creation, approval-gated
inventory and price writes, and grounded SOP/manual questions.

The live evaluator records exact tool and status sequences, approval correctness, required
knowledge sections, tokens, latency, and optional cost. No checked-in score exists until the suite
is run with a real `OPENAI_API_KEY`; absence of a key is a hard failure rather than a synthetic
result.
