"""Pricing and work-order domain models used by Copilot tools."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from smart_retail.domain.inventory import DomainValidationError


def _required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DomainValidationError(f"{field_name} must not be blank")
    return normalized


@dataclass(frozen=True, slots=True)
class PriceChange:
    request_id: str
    store_id: str
    sku: str
    new_price: Decimal
    reason: str
    currency: str = "USD"

    def __post_init__(self) -> None:
        for field_name in ("request_id", "store_id", "sku", "reason"):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))
        currency = _required(self.currency, "currency").upper()
        if len(currency) != 3:
            raise DomainValidationError("currency must be a three-letter code")
        object.__setattr__(self, "currency", currency)
        if self.new_price <= 0:
            raise DomainValidationError("new_price must be positive")


@dataclass(frozen=True, slots=True)
class PriceRecord:
    store_id: str
    sku: str
    amount: Decimal
    currency: str
    updated_at: datetime


class WorkOrderPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class WorkOrderStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class WorkOrderRequest:
    request_id: str
    store_id: str
    category: str
    priority: WorkOrderPriority
    summary: str

    def __post_init__(self) -> None:
        for field_name in ("request_id", "store_id", "category", "summary"):
            object.__setattr__(self, field_name, _required(getattr(self, field_name), field_name))


@dataclass(frozen=True, slots=True)
class WorkOrder:
    ticket_id: str
    store_id: str
    category: str
    priority: WorkOrderPriority
    status: WorkOrderStatus
    summary: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
