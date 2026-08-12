"""Reproducible evaluation for inventory anomaly detectors."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    precision_score,
    recall_score,
    root_mean_squared_error,
)

from smart_retail.analytics.anomalies import InventoryAnomalyDetector
from smart_retail.analytics.contracts import DailyRetailMetric
from smart_retail.analytics.forecasting import DemandForecaster


@dataclass(frozen=True, slots=True)
class AnomalyEvaluationMetrics:
    detector: str
    cases: int
    positive_cases: int
    precision: float
    recall: float
    f1: float
    accuracy: float


@dataclass(frozen=True, slots=True)
class ForecastEvaluationMetrics:
    forecaster: str
    cases: int
    mae: float
    rmse: float
    wape: float
    mean_bias: float


def evaluate_anomaly_detector(
    records: Sequence[DailyRetailMetric],
    detector: InventoryAnomalyDetector,
) -> AnomalyEvaluationMetrics:
    labeled = [record for record in records if record.expected_anomaly is not None]
    if not labeled:
        raise ValueError("evaluation requires at least one labeled record")

    predictions = {
        result.key: result.is_anomaly
        for result in detector.detect(labeled)
    }
    expected = [int(cast(bool, record.expected_anomaly)) for record in labeled]
    predicted = [int(predictions[record.key]) for record in labeled]

    return AnomalyEvaluationMetrics(
        detector=detector.name,
        cases=len(labeled),
        positive_cases=sum(expected),
        precision=float(precision_score(expected, predicted, zero_division="warn")),
        recall=float(recall_score(expected, predicted, zero_division="warn")),
        f1=float(f1_score(expected, predicted, zero_division="warn")),
        accuracy=float(accuracy_score(expected, predicted)),
    )


def evaluate_forecaster(
    records: Sequence[DailyRetailMetric],
    forecaster: DemandForecaster,
) -> ForecastEvaluationMetrics:
    forecasts = forecaster.forecast(records)
    if not forecasts:
        raise ValueError("forecast evaluation requires observations after the history window")

    observed = [result.observed_units for result in forecasts]
    predicted = [result.predicted_units for result in forecasts]
    observed_total = sum(observed)
    if observed_total == 0:
        raise ValueError("WAPE is undefined when total observed demand is zero")

    absolute_error_total = sum(
        abs(actual - estimate) for actual, estimate in zip(observed, predicted, strict=True)
    )
    mean_bias = sum(
        estimate - actual for actual, estimate in zip(observed, predicted, strict=True)
    ) / len(forecasts)
    return ForecastEvaluationMetrics(
        forecaster=forecaster.name,
        cases=len(forecasts),
        mae=float(mean_absolute_error(observed, predicted)),
        rmse=float(root_mean_squared_error(observed, predicted)),
        wape=absolute_error_total / observed_total,
        mean_bias=mean_bias,
    )
