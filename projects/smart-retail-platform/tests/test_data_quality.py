from pathlib import Path

import pytest

from smart_retail.analytics.data_quality import DataQualityError, load_daily_metrics

EVALUATION_DATASET = (
    Path(__file__).parents[1] / "data" / "evaluation" / "inventory_anomalies_v1.csv"
)


def test_versioned_evaluation_dataset_passes_quality_checks() -> None:
    loaded = load_daily_metrics(EVALUATION_DATASET)

    assert loaded.report.passed
    assert loaded.report.total_rows == 30
    assert loaded.report.valid_rows == 30
    assert all(record.expected_anomaly is not None for record in loaded.records)


def test_non_strict_loading_reports_invalid_and_duplicate_rows(tmp_path: Path) -> None:
    dataset = tmp_path / "invalid.csv"
    dataset.write_text(
        "business_date,store_id,sku,units_sold,ending_inventory,unit_price\n"
        "2026-07-01,store-1,sku-1,10,20,3.99\n"
        "2026-07-01,store-1,sku-1,10,20,3.99\n"
        "2026-07-02,store-1,sku-1,-1,19,3.99\n",
        encoding="utf-8",
    )

    loaded = load_daily_metrics(dataset, strict=False)

    assert not loaded.report.passed
    assert loaded.report.valid_rows == 1
    assert loaded.report.invalid_rows == 2
    assert loaded.report.duplicate_rows == 1
    assert len(loaded.report.issues) == 2


def test_strict_loading_rejects_invalid_dataset(tmp_path: Path) -> None:
    dataset = tmp_path / "invalid.csv"
    dataset.write_text(
        "business_date,store_id,sku,units_sold,ending_inventory,unit_price\n"
        "2026-07-01,store-1,sku-1,10,-1,3.99\n",
        encoding="utf-8",
    )

    with pytest.raises(DataQualityError) as raised:
        load_daily_metrics(dataset)

    assert raised.value.report.invalid_rows == 1
