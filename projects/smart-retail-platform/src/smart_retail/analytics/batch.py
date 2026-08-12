"""Build and persist one repeatable inventory intelligence batch run."""

import argparse
import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from smart_retail.analytics.anomalies import InventoryAnomalyResult, InventoryRiskRulesDetector
from smart_retail.analytics.contracts import DailyRetailMetric
from smart_retail.analytics.data_quality import load_daily_metrics
from smart_retail.analytics.forecasting import DemandForecast, TrailingMeanForecaster
from smart_retail.analytics.results import AnalyticsRun
from smart_retail.repositories.base import RetailRepository


@dataclass(frozen=True, slots=True)
class InventoryIntelligenceBatch:
    run: AnalyticsRun
    anomalies: tuple[InventoryAnomalyResult, ...]
    forecasts: tuple[DemandForecast, ...]


def build_inventory_intelligence_batch(
    records: Sequence[DailyRetailMetric],
    *,
    dataset_version: str,
    run_id: str | None = None,
    created_at: datetime | None = None,
) -> InventoryIntelligenceBatch:
    detector = InventoryRiskRulesDetector()
    forecaster = TrailingMeanForecaster()
    anomalies = tuple(result for result in detector.detect(records) if result.is_anomaly)
    forecasts = tuple(forecaster.forecast(records))
    run_identifier = run_id or f"analytics-{uuid4().hex}"
    if created_at is None:
        run = AnalyticsRun(
            run_id=run_identifier,
            dataset_version=dataset_version,
            input_rows=len(records),
            anomaly_detector="inventory_risk_rules:v1",
            forecaster="trailing_mean:history_days=7,minimum_history=3",
        )
    else:
        run = AnalyticsRun(
            run_id=run_identifier,
            dataset_version=dataset_version,
            input_rows=len(records),
            anomaly_detector="inventory_risk_rules:v1",
            forecaster="trailing_mean:history_days=7,minimum_history=3",
            created_at=created_at,
        )
    return InventoryIntelligenceBatch(run=run, anomalies=anomalies, forecasts=forecasts)


def persist_inventory_intelligence_batch(
    repository: RetailRepository,
    batch: InventoryIntelligenceBatch,
) -> AnalyticsRun:
    return repository.save_analytics_run(batch.run, batch.anomalies, batch.forecasts)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run and persist inventory intelligence")
    parser.add_argument("dataset", type=Path, help="validated daily retail CSV")
    parser.add_argument("--dataset-version", help="defaults to the dataset filename stem")
    parser.add_argument("--run-id", help="optional caller-supplied unique run identifier")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    dataset_path = cast(Path, args.dataset)
    database_url = cast(str | None, args.database_url)
    if not database_url:
        raise SystemExit("DATABASE_URL or --database-url is required to persist a batch")

    loaded = load_daily_metrics(dataset_path)
    batch = build_inventory_intelligence_batch(
        loaded.records,
        dataset_version=cast(str | None, args.dataset_version) or dataset_path.stem,
        run_id=cast(str | None, args.run_id),
    )

    from smart_retail.repositories.postgres import (
        PostgresRetailRepository,
        build_session_factory,
    )

    repository = PostgresRetailRepository(build_session_factory(database_url))
    persisted = persist_inventory_intelligence_batch(repository, batch)
    output = {
        "run": asdict(persisted),
        "anomalies_persisted": len(batch.anomalies),
        "forecasts_persisted": len(batch.forecasts),
    }
    print(json.dumps(output, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
