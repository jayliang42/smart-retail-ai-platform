"""Typed records shared by data-quality, anomaly, and forecasting workflows."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class DailyRetailMetric:
    """Canonical daily sales and ending-inventory observation."""

    business_date: date
    store_id: str
    sku: str
    units_sold: int
    ending_inventory: int
    unit_price: Decimal
    expected_anomaly: bool | None = None

    @property
    def key(self) -> tuple[str, str, date]:
        return (self.store_id, self.sku, self.business_date)


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    issues: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.invalid_rows == 0 and self.duplicate_rows == 0


@dataclass(frozen=True, slots=True)
class LoadedDailyDataset:
    records: tuple[DailyRetailMetric, ...]
    report: DataQualityReport
