"""Device registration and event domain models."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from smart_retail.domain.inventory import DomainValidationError


def _normalized_required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DomainValidationError(f"{field_name} must not be blank")
    return normalized


class DeviceType(StrEnum):
    REFRIGERATION_UNIT = "refrigeration_unit"
    TEMPERATURE_SENSOR = "temperature_sensor"
    POS_TERMINAL = "pos_terminal"
    CAMERA = "camera"
    EDGE_GATEWAY = "edge_gateway"
    OTHER = "other"


class DeviceStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"


@dataclass(frozen=True, slots=True)
class Device:
    """A store-associated device registered with the platform."""

    device_id: str
    store_id: str
    device_type: DeviceType
    display_name: str
    status: DeviceStatus = DeviceStatus.ACTIVE
    registered_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        object.__setattr__(self, "device_id", _normalized_required(self.device_id, "device_id"))
        object.__setattr__(self, "store_id", _normalized_required(self.store_id, "store_id"))
        object.__setattr__(
            self,
            "display_name",
            _normalized_required(self.display_name, "display_name"),
        )
        _require_timezone(self.registered_at, "registered_at")


@dataclass(frozen=True, slots=True)
class DeviceEvent:
    """An idempotent observation emitted by a registered device."""

    event_id: str
    device_id: str
    event_type: str
    observed_at: datetime
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _normalized_required(self.event_id, "event_id"))
        object.__setattr__(self, "device_id", _normalized_required(self.device_id, "device_id"))
        object.__setattr__(
            self,
            "event_type",
            _normalized_required(self.event_type, "event_type"),
        )
        _require_timezone(self.observed_at, "observed_at")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class DeviceEventRecord:
    """A device event plus the platform receipt timestamp."""

    event_id: str
    device_id: str
    event_type: str
    observed_at: datetime
    received_at: datetime
    payload: Mapping[str, object]


def _require_timezone(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{field_name} must include a timezone")
