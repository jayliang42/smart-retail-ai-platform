import pytest

from smart_retail.domain import (
    DomainValidationError,
    InventoryAdjustment,
    InventoryWouldBecomeNegativeError,
)


def adjustment(**overrides: object) -> InventoryAdjustment:
    values: dict[str, object] = {
        "request_id": "request-1",
        "store_id": "store-1",
        "sku": "sku-1",
        "quantity_delta": 5,
        "reason": "delivery",
    }
    values.update(overrides)
    return InventoryAdjustment(**values)  # type: ignore[arg-type]


def test_applies_valid_adjustment() -> None:
    assert adjustment(quantity_delta=-3).apply(10) == 7


@pytest.mark.parametrize("field", ["request_id", "store_id", "sku", "reason"])
def test_rejects_blank_required_text(field: str) -> None:
    with pytest.raises(DomainValidationError, match=field):
        adjustment(**{field: "   "})


def test_rejects_zero_delta() -> None:
    with pytest.raises(DomainValidationError, match="non-zero"):
        adjustment(quantity_delta=0)


def test_rejects_non_integer_delta() -> None:
    with pytest.raises(DomainValidationError, match="integer"):
        adjustment(quantity_delta=1.5)


def test_rejects_negative_result() -> None:
    with pytest.raises(InventoryWouldBecomeNegativeError):
        adjustment(quantity_delta=-6).apply(5)
