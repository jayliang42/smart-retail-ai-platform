from datetime import UTC, datetime
from decimal import Decimal

import pytest

from smart_retail.domain import (
    Device,
    DeviceEvent,
    DeviceType,
    InventoryAdjustment,
    PriceChange,
    Sku,
    Store,
    WorkOrderPriority,
    WorkOrderRequest,
)
from smart_retail.repositories.base import IdempotencyConflictError, ResourceNotFoundError
from smart_retail.repositories.memory import InMemoryRetailRepository


def configured_repository() -> InMemoryRetailRepository:
    repository = InMemoryRetailRepository()
    repository.create_store(Store("store-1", "Chicago Loop"))
    repository.create_sku(Sku("sku-1", "Milk"))
    return repository


def test_adjustment_is_idempotent() -> None:
    repository = configured_repository()
    request = InventoryAdjustment("request-1", "store-1", "sku-1", 5, "delivery")

    first = repository.adjust_inventory(request)
    second = repository.adjust_inventory(request)

    assert first == second
    assert repository.get_inventory("store-1", "sku-1") == first


def test_reused_request_id_with_different_payload_conflicts() -> None:
    repository = configured_repository()
    repository.adjust_inventory(
        InventoryAdjustment("request-1", "store-1", "sku-1", 5, "delivery")
    )

    with pytest.raises(IdempotencyConflictError):
        repository.adjust_inventory(
            InventoryAdjustment("request-1", "store-1", "sku-1", 6, "delivery")
        )


def test_unknown_store_is_rejected() -> None:
    repository = configured_repository()

    with pytest.raises(ResourceNotFoundError, match="store"):
        repository.adjust_inventory(
            InventoryAdjustment("request-1", "missing", "sku-1", 5, "delivery")
        )


def test_device_event_is_idempotent_and_listed() -> None:
    repository = configured_repository()
    repository.create_device(
        Device(
            device_id="sensor-1",
            store_id="store-1",
            device_type=DeviceType.TEMPERATURE_SENSOR,
            display_name="Dairy sensor",
        )
    )
    event = DeviceEvent(
        event_id="event-1",
        device_id="sensor-1",
        event_type="temperature_reading",
        observed_at=datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
        payload={"temperature_c": 3.2},
    )

    first = repository.record_device_event(event)
    replay = repository.record_device_event(event)

    assert first == replay
    assert repository.list_device_events("sensor-1", limit=10) == [first]


def test_device_event_id_conflicts_for_different_payload() -> None:
    repository = configured_repository()
    repository.create_device(
        Device(
            device_id="sensor-1",
            store_id="store-1",
            device_type=DeviceType.TEMPERATURE_SENSOR,
            display_name="Dairy sensor",
        )
    )
    observed_at = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
    repository.record_device_event(
        DeviceEvent(
            "event-1",
            "sensor-1",
            "temperature_reading",
            observed_at,
            {"temperature_c": 3.2},
        )
    )

    with pytest.raises(IdempotencyConflictError, match="event_id"):
        repository.record_device_event(
            DeviceEvent(
                "event-1",
                "sensor-1",
                "temperature_reading",
                observed_at,
                {"temperature_c": 8.0},
            )
        )


def test_price_and_work_order_operations_are_idempotent() -> None:
    repository = configured_repository()
    price_change = PriceChange(
        "price-1", "store-1", "sku-1", Decimal("3.49"), "approved promotion"
    )
    work_order_request = WorkOrderRequest(
        "ticket-1",
        "store-1",
        "refrigeration",
        WorkOrderPriority.HIGH,
        "Dairy case above 5 C",
    )

    price = repository.set_price(price_change)
    price_replay = repository.set_price(price_change)
    work_order = repository.create_work_order(work_order_request)
    work_order_replay = repository.create_work_order(work_order_request)

    assert price_replay == price
    assert repository.get_price("store-1", "sku-1") == price
    assert work_order_replay == work_order
    assert repository.get_work_order("ticket-1") == work_order
