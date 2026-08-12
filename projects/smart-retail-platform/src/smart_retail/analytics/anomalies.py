"""Transparent inventory anomaly baselines."""

from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import ClassVar, Protocol

from smart_retail.analytics.contracts import DailyRetailMetric


@dataclass(frozen=True, slots=True)
class InventoryAnomalyResult:
    store_id: str
    sku: str
    business_date: date
    is_anomaly: bool
    reasons: tuple[str, ...]
    trailing_demand: float | None

    @property
    def key(self) -> tuple[str, str, date]:
        return (self.store_id, self.sku, self.business_date)


class InventoryAnomalyDetector(Protocol):
    name: ClassVar[str]

    def detect(self, records: Sequence[DailyRetailMetric]) -> list[InventoryAnomalyResult]: ...


@dataclass(frozen=True, slots=True)
class StockoutOnlyDetector:
    """Minimal baseline that flags only zero inventory with positive sales."""

    name: ClassVar[str] = "stockout_only"

    def detect(self, records: Sequence[DailyRetailMetric]) -> list[InventoryAnomalyResult]:
        return [
            InventoryAnomalyResult(
                store_id=record.store_id,
                sku=record.sku,
                business_date=record.business_date,
                is_anomaly=record.ending_inventory == 0 and record.units_sold > 0,
                reasons=("stockout",)
                if record.ending_inventory == 0 and record.units_sold > 0
                else (),
                trailing_demand=None,
            )
            for record in records
        ]


@dataclass(frozen=True, slots=True)
class InventoryRiskRulesDetector:
    """Explainable baseline using recent demand, inventory coverage, and demand spikes."""

    history_days: int = 7
    minimum_history: int = 3
    coverage_days: float = 1.0
    spike_multiplier: float = 2.0

    name: ClassVar[str] = "inventory_risk_rules"

    def __post_init__(self) -> None:
        if self.history_days < 1:
            raise ValueError("history_days must be positive")
        if not 1 <= self.minimum_history <= self.history_days:
            raise ValueError("minimum_history must be between 1 and history_days")
        if self.coverage_days <= 0 or self.spike_multiplier <= 1:
            raise ValueError("coverage_days must be positive and spike_multiplier must exceed 1")

    def detect(self, records: Sequence[DailyRetailMetric]) -> list[InventoryAnomalyResult]:
        grouped: dict[tuple[str, str], list[DailyRetailMetric]] = defaultdict(list)
        for record in records:
            grouped[(record.store_id, record.sku)].append(record)

        results: list[InventoryAnomalyResult] = []
        for group in grouped.values():
            history: deque[int] = deque(maxlen=self.history_days)
            for record in sorted(group, key=lambda item: item.business_date):
                trailing_demand = (
                    sum(history) / len(history) if len(history) >= self.minimum_history else None
                )
                reasons: list[str] = []
                if trailing_demand is not None and trailing_demand > 0:
                    if record.ending_inventory == 0:
                        reasons.append("stockout")
                    elif record.ending_inventory <= trailing_demand * self.coverage_days:
                        reasons.append("low_stock_coverage")
                    if record.units_sold > trailing_demand * self.spike_multiplier:
                        reasons.append("demand_spike")

                results.append(
                    InventoryAnomalyResult(
                        store_id=record.store_id,
                        sku=record.sku,
                        business_date=record.business_date,
                        is_anomaly=bool(reasons),
                        reasons=tuple(reasons),
                        trailing_demand=trailing_demand,
                    )
                )
                history.append(record.units_sold)

        results.sort(key=lambda item: (item.business_date, item.store_id, item.sku))
        return results
