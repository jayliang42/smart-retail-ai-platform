"""Retail domain models."""

from smart_retail.domain.approvals import ActorRole, ApprovalRequest, ApprovalStatus
from smart_retail.domain.audit import AuditActor, OperationAuditEvent
from smart_retail.domain.devices import (
    Device,
    DeviceEvent,
    DeviceEventRecord,
    DeviceStatus,
    DeviceType,
)
from smart_retail.domain.inventory import (
    DomainValidationError,
    InventoryAdjustment,
    InventorySnapshot,
    InventoryWouldBecomeNegativeError,
    Sku,
    Store,
)
from smart_retail.domain.operations import (
    PriceChange,
    PriceRecord,
    WorkOrder,
    WorkOrderPriority,
    WorkOrderRequest,
    WorkOrderStatus,
)

__all__ = [
    "ActorRole",
    "ApprovalRequest",
    "ApprovalStatus",
    "AuditActor",
    "Device",
    "DeviceEvent",
    "DeviceEventRecord",
    "DeviceStatus",
    "DeviceType",
    "DomainValidationError",
    "InventoryAdjustment",
    "InventorySnapshot",
    "InventoryWouldBecomeNegativeError",
    "OperationAuditEvent",
    "PriceChange",
    "PriceRecord",
    "Sku",
    "Store",
    "WorkOrder",
    "WorkOrderPriority",
    "WorkOrderRequest",
    "WorkOrderStatus",
]
