from decimal import Decimal

import pytest

from smart_retail.domain import (
    DomainValidationError,
    PriceChange,
    WorkOrderPriority,
    WorkOrderRequest,
)


def test_price_change_requires_positive_price_and_normalizes_currency() -> None:
    change = PriceChange("price-1", "store-1", "sku-1", Decimal("3.49"), "promotion", "usd")

    assert change.currency == "USD"

    with pytest.raises(DomainValidationError, match="positive"):
        PriceChange("price-2", "store-1", "sku-1", Decimal("0"), "invalid")


def test_work_order_requires_non_blank_summary() -> None:
    with pytest.raises(DomainValidationError, match="summary"):
        WorkOrderRequest("ticket-1", "store-1", "refrigeration", WorkOrderPriority.HIGH, " ")
