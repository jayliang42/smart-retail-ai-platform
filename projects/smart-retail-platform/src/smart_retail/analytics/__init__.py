"""Inventory intelligence data and evaluation workflows."""

from smart_retail.analytics.anomalies import (
    InventoryAnomalyResult,
    InventoryRiskRulesDetector,
    StockoutOnlyDetector,
)
from smart_retail.analytics.contracts import DailyRetailMetric
from smart_retail.analytics.data_quality import DataQualityError, load_daily_metrics
from smart_retail.analytics.evaluation import (
    AnomalyEvaluationMetrics,
    ForecastEvaluationMetrics,
    evaluate_anomaly_detector,
    evaluate_forecaster,
)
from smart_retail.analytics.forecasting import (
    DemandForecast,
    LastValueForecaster,
    TrailingMeanForecaster,
)

__all__ = [
    "AnomalyEvaluationMetrics",
    "DailyRetailMetric",
    "DataQualityError",
    "DemandForecast",
    "ForecastEvaluationMetrics",
    "InventoryAnomalyResult",
    "InventoryRiskRulesDetector",
    "LastValueForecaster",
    "StockoutOnlyDetector",
    "TrailingMeanForecaster",
    "evaluate_anomaly_detector",
    "evaluate_forecaster",
    "load_daily_metrics",
]
