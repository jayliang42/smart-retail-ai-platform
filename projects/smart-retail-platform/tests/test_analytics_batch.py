from datetime import UTC, datetime
from pathlib import Path

from smart_retail.analytics.batch import (
    build_inventory_intelligence_batch,
    persist_inventory_intelligence_batch,
)
from smart_retail.analytics.data_quality import load_daily_metrics
from smart_retail.repositories.memory import InMemoryRetailRepository

EVALUATION_DATASET = (
    Path(__file__).parents[1] / "data" / "evaluation" / "inventory_anomalies_v1.csv"
)


def test_batch_builds_and_persists_versioned_results() -> None:
    records = load_daily_metrics(EVALUATION_DATASET).records
    repository = InMemoryRetailRepository()
    batch = build_inventory_intelligence_batch(
        records,
        dataset_version="inventory_anomalies_v1",
        run_id="run-1",
        created_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
    )

    persisted = persist_inventory_intelligence_batch(repository, batch)

    assert persisted == batch.run
    assert persisted.input_rows == 30
    assert len(batch.anomalies) == 11
    assert len(batch.forecasts) == 24
    assert repository.get_analytics_run("run-1") == persisted
    assert len(
        repository.list_inventory_anomalies(
            "run-1", store_id="store-1", sku="milk-1", limit=100
        )
    ) == 5
    assert len(
        repository.list_demand_forecasts(
            "run-1", store_id="store-1", sku="milk-1", limit=100
        )
    ) == 12
