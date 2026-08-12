"""CSV loading and data-quality validation for daily retail metrics."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from smart_retail.analytics.contracts import (
    DailyRetailMetric,
    DataQualityReport,
    LoadedDailyDataset,
)

REQUIRED_COLUMNS = {
    "business_date",
    "store_id",
    "sku",
    "units_sold",
    "ending_inventory",
    "unit_price",
}


class DataQualityError(ValueError):
    """Raised when strict loading encounters invalid or duplicate rows."""

    def __init__(self, report: DataQualityReport) -> None:
        super().__init__("daily retail dataset failed data-quality validation")
        self.report = report


class _DailyRetailMetricRow(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    business_date: date
    store_id: str = Field(min_length=1, max_length=64)
    sku: str = Field(min_length=1, max_length=64)
    units_sold: int = Field(ge=0)
    ending_inventory: int = Field(ge=0)
    unit_price: Decimal = Field(gt=0)
    expected_anomaly: bool | None = None

    @field_validator("expected_anomaly", mode="before")
    @classmethod
    def blank_label_is_missing(cls, value: object) -> object:
        return None if value == "" else value


def load_daily_metrics(path: Path, *, strict: bool = True) -> LoadedDailyDataset:
    """Load a CSV into canonical records and return an explicit quality report."""

    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing_columns = sorted(REQUIRED_COLUMNS.difference(frame.columns))
    if missing_columns:
        report = DataQualityReport(
            total_rows=len(frame),
            valid_rows=0,
            invalid_rows=len(frame),
            duplicate_rows=0,
            issues=(f"missing required columns: {', '.join(missing_columns)}",),
        )
        raise DataQualityError(report)

    raw_rows = cast(list[dict[str, object]], frame.to_dict(orient="records"))
    records: list[DailyRetailMetric] = []
    issues: list[str] = []
    duplicate_rows = 0
    seen_keys: set[tuple[str, str, date]] = set()

    for row_number, raw_row in enumerate(raw_rows, start=2):
        try:
            parsed = _DailyRetailMetricRow.model_validate(raw_row)
        except ValidationError as error:
            summary = "; ".join(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                for item in error.errors()
            )
            issues.append(f"row {row_number}: {summary}")
            continue

        record = DailyRetailMetric(
            business_date=parsed.business_date,
            store_id=parsed.store_id,
            sku=parsed.sku,
            units_sold=parsed.units_sold,
            ending_inventory=parsed.ending_inventory,
            unit_price=parsed.unit_price,
            expected_anomaly=parsed.expected_anomaly,
        )
        if record.key in seen_keys:
            duplicate_rows += 1
            issues.append(
                f"row {row_number}: duplicate business_date/store_id/sku key {record.key}"
            )
            continue
        seen_keys.add(record.key)
        records.append(record)

    invalid_rows = len(raw_rows) - len(records)
    report = DataQualityReport(
        total_rows=len(raw_rows),
        valid_rows=len(records),
        invalid_rows=invalid_rows,
        duplicate_rows=duplicate_rows,
        issues=tuple(issues),
    )
    loaded = LoadedDailyDataset(records=tuple(records), report=report)
    if strict and not report.passed:
        raise DataQualityError(report)
    return loaded
