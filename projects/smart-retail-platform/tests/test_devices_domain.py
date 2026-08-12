from datetime import UTC, datetime

import pytest

from smart_retail.domain import (
    Device,
    DeviceEvent,
    DeviceStatus,
    DeviceType,
    DomainValidationError,
)


def test_device_defaults_to_active_and_normalizes_text() -> None:
    device = Device(
        device_id=" sensor-1 ",
        store_id=" store-1 ",
        device_type=DeviceType.TEMPERATURE_SENSOR,
        display_name=" Dairy cooler sensor ",
    )

    assert device.device_id == "sensor-1"
    assert device.store_id == "store-1"
    assert device.display_name == "Dairy cooler sensor"
    assert device.status is DeviceStatus.ACTIVE


def test_event_requires_timezone_aware_observation() -> None:
    with pytest.raises(DomainValidationError, match="timezone"):
        DeviceEvent(
            event_id="event-1",
            device_id="sensor-1",
            event_type="temperature_reading",
            observed_at=datetime(2026, 8, 11, 10, 0),
            payload={"temperature_c": 3.2},
        )


def test_event_copies_top_level_payload() -> None:
    payload: dict[str, object] = {"temperature_c": 3.2}
    event = DeviceEvent(
        event_id="event-1",
        device_id="sensor-1",
        event_type="temperature_reading",
        observed_at=datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
        payload=payload,
    )

    payload["temperature_c"] = 99.0

    assert event.payload["temperature_c"] == 3.2
