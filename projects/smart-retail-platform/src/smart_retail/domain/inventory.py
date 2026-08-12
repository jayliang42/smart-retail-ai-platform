"""Inventory domain models and invariants."""

from dataclasses import dataclass
from datetime import datetime


class DomainValidationError(ValueError):
    """Raised when a domain object would be invalid."""


class InventoryWouldBecomeNegativeError(DomainValidationError):
    """Raised when an adjustment would produce negative inventory."""


def _normalized_required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DomainValidationError(f"{field_name} must not be blank")
    return normalized


@dataclass(frozen=True, slots=True)
class Store:
    """A retail store that owns inventory."""

    store_id: str
    name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "store_id", _normalized_required(self.store_id, "store_id"))
        object.__setattr__(self, "name", _normalized_required(self.name, "name"))


@dataclass(frozen=True, slots=True)
class Sku:
    """A sellable stock-keeping unit."""

    sku: str
    name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "sku", _normalized_required(self.sku, "sku"))
        object.__setattr__(self, "name", _normalized_required(self.name, "name"))


@dataclass(frozen=True, slots=True)
class InventoryAdjustment:
    """An idempotent request to change inventory for one store and SKU."""

    request_id: str
    store_id: str
    sku: str
    quantity_delta: int
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _normalized_required(self.request_id, "request_id")
        )
        object.__setattr__(self, "store_id", _normalized_required(self.store_id, "store_id"))
        object.__setattr__(self, "sku", _normalized_required(self.sku, "sku"))
        object.__setattr__(self, "reason", _normalized_required(self.reason, "reason"))
        if type(self.quantity_delta) is not int or self.quantity_delta == 0:
            raise DomainValidationError("quantity_delta must be a non-zero integer")

    def apply(self, current_quantity: int) -> int:
        """Return the new quantity while protecting the non-negative invariant."""

        if type(current_quantity) is not int or current_quantity < 0:
            raise DomainValidationError("current_quantity must be a non-negative integer")
        new_quantity = current_quantity + self.quantity_delta
        if new_quantity < 0:
            raise InventoryWouldBecomeNegativeError(
                f"adjustment would reduce inventory below zero: {current_quantity} "
                f"+ ({self.quantity_delta})"
            )
        return new_quantity


@dataclass(frozen=True, slots=True)
class InventorySnapshot:
    """Inventory state returned by repositories and API handlers."""

    store_id: str
    sku: str
    quantity: int
    updated_at: datetime
