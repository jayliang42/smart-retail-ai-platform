"""Persistent metadata for repeatable inventory intelligence batch runs."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class AnalyticsRun:
    run_id: str
    dataset_version: str
    input_rows: int
    anomaly_detector: str
    forecaster: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        text_fields = (
            self.run_id,
            self.dataset_version,
            self.anomaly_detector,
            self.forecaster,
        )
        if any(not value.strip() for value in text_fields):
            raise ValueError("analytics run identifiers and configurations cannot be blank")
        if self.input_rows < 0:
            raise ValueError("input_rows cannot be negative")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
