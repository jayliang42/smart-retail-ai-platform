from pathlib import Path

from smart_retail.analytics.anomalies import (
    InventoryRiskRulesDetector,
    StockoutOnlyDetector,
)
from smart_retail.analytics.data_quality import load_daily_metrics
from smart_retail.analytics.evaluation import evaluate_anomaly_detector

EVALUATION_DATASET = (
    Path(__file__).parents[1] / "data" / "evaluation" / "inventory_anomalies_v1.csv"
)


def test_risk_rules_outperform_stockout_only_baseline() -> None:
    records = load_daily_metrics(EVALUATION_DATASET).records

    stockout = evaluate_anomaly_detector(records, StockoutOnlyDetector())
    risk_rules = evaluate_anomaly_detector(records, InventoryRiskRulesDetector())

    assert risk_rules.f1 > stockout.f1
    assert risk_rules.recall == 1.0
    assert risk_rules.precision == 1.0


def test_detector_provides_explainable_reasons_without_future_leakage() -> None:
    records = load_daily_metrics(EVALUATION_DATASET).records
    results = InventoryRiskRulesDetector().detect(records)
    by_key = {result.key: result for result in results}
    milk_records = [record for record in records if record.sku == "milk-1"]

    first = by_key[milk_records[0].key]
    low_stock = by_key[milk_records[5].key]
    spike = by_key[milk_records[8].key]

    assert first.trailing_demand is None
    assert not first.is_anomaly
    assert low_stock.reasons == ("low_stock_coverage",)
    assert spike.reasons == ("demand_spike",)
