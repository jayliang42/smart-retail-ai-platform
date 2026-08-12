"""Leakage-safe one-step demand forecasting baselines."""

from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import ClassVar, Protocol

from smart_retail.analytics.contracts import DailyRetailMetric


@dataclass(frozen=True, slots=True)
class DemandForecast:
    store_id: str
    sku: str
    target_date: date
    predicted_units: float
    observed_units: int
    history_size: int

    @property
    def key(self) -> tuple[str, str, date]:
        return (self.store_id, self.sku, self.target_date)


class DemandForecaster(Protocol):
    name: ClassVar[str]

    def forecast(self, records: Sequence[DailyRetailMetric]) -> list[DemandForecast]: ...


@dataclass(frozen=True, slots=True)
class LastValueForecaster:
    """Predict the next observation from the most recent observed demand."""

    minimum_history: int = 3

    name: ClassVar[str] = "last_value"

    def __post_init__(self) -> None:
        if self.minimum_history < 1:
            raise ValueError("minimum_history must be positive")

    def forecast(self, records: Sequence[DailyRetailMetric]) -> list[DemandForecast]:
        grouped = _group_by_store_sku(records)
        forecasts: list[DemandForecast] = []
        for group in grouped.values():
            history: list[int] = []
            for record in sorted(group, key=lambda item: item.business_date):
                if len(history) >= self.minimum_history:
                    forecasts.append(
                        _forecast_result(record, float(history[-1]), len(history))
                    )
                history.append(record.units_sold)
        return _sort_forecasts(forecasts)


@dataclass(frozen=True, slots=True)
class TrailingMeanForecaster:
    """Predict from a bounded mean of demand observed before the target date."""

    history_days: int = 7
    minimum_history: int = 3

    name: ClassVar[str] = "trailing_mean"

    def __post_init__(self) -> None:
        if self.history_days < 1:
            raise ValueError("history_days must be positive")
        if not 1 <= self.minimum_history <= self.history_days:
            raise ValueError("minimum_history must be between 1 and history_days")

    def forecast(self, records: Sequence[DailyRetailMetric]) -> list[DemandForecast]:
        grouped = _group_by_store_sku(records)
        forecasts: list[DemandForecast] = []
        for group in grouped.values():
            history: deque[int] = deque(maxlen=self.history_days)
            for record in sorted(group, key=lambda item: item.business_date):
                if len(history) >= self.minimum_history:
                    forecasts.append(
                        _forecast_result(record, sum(history) / len(history), len(history))
                    )
                history.append(record.units_sold)
        return _sort_forecasts(forecasts)


def _group_by_store_sku(
    records: Sequence[DailyRetailMetric],
) -> dict[tuple[str, str], list[DailyRetailMetric]]:
    grouped: dict[tuple[str, str], list[DailyRetailMetric]] = defaultdict(list)
    for record in records:
        grouped[(record.store_id, record.sku)].append(record)
    return grouped


def _forecast_result(
    record: DailyRetailMetric, predicted_units: float, history_size: int
) -> DemandForecast:
    return DemandForecast(
        store_id=record.store_id,
        sku=record.sku,
        target_date=record.business_date,
        predicted_units=predicted_units,
        observed_units=record.units_sold,
        history_size=history_size,
    )


def _sort_forecasts(forecasts: list[DemandForecast]) -> list[DemandForecast]:
    forecasts.sort(key=lambda item: (item.target_date, item.store_id, item.sku))
    return forecasts
