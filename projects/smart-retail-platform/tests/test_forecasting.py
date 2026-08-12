from pathlib import Path

import pytest

from smart_retail.analytics.data_quality import load_daily_metrics
from smart_retail.analytics.evaluation import evaluate_forecaster
from smart_retail.analytics.forecasting import LastValueForecaster, TrailingMeanForecaster

EVALUATION_DATASET = (
    Path(__file__).parents[1] / "data" / "evaluation" / "inventory_anomalies_v1.csv"
)


def test_forecasts_use_only_observations_before_the_target_date() -> None:
    records = load_daily_metrics(EVALUATION_DATASET).records
    milk_records = [record for record in records if record.sku == "milk-1"]

    last_value = LastValueForecaster().forecast(milk_records)[0]
    trailing_mean = TrailingMeanForecaster().forecast(milk_records)[0]

    assert last_value.target_date == milk_records[3].business_date
    assert last_value.predicted_units == 9.0
    assert trailing_mean.target_date == milk_records[3].business_date
    assert trailing_mean.predicted_units == pytest.approx(10.0)
    assert trailing_mean.history_size == 3


def test_walk_forward_evaluation_compares_the_same_cases() -> None:
    records = load_daily_metrics(EVALUATION_DATASET).records

    last_value = evaluate_forecaster(records, LastValueForecaster())
    trailing_mean = evaluate_forecaster(records, TrailingMeanForecaster())

    assert last_value.cases == 24
    assert trailing_mean.cases == last_value.cases
    assert last_value.mae > 0
    assert trailing_mean.mae > 0
    assert last_value.wape > 0
    assert trailing_mean.wape > 0


@pytest.mark.parametrize(
    ("forecaster", "message"),
    [
        (LastValueForecaster(minimum_history=3), "observations after the history window"),
        (TrailingMeanForecaster(minimum_history=3), "observations after the history window"),
    ],
)
def test_evaluation_rejects_too_little_history(
    forecaster: LastValueForecaster | TrailingMeanForecaster,
    message: str,
) -> None:
    records = load_daily_metrics(EVALUATION_DATASET).records[:2]

    with pytest.raises(ValueError, match=message):
        evaluate_forecaster(records, forecaster)
