"""Persistence boundary for retail operations and analytics results."""

from collections.abc import Sequence
from typing import Protocol

from smart_retail.analytics.anomalies import InventoryAnomalyResult
from smart_retail.analytics.forecasting import DemandForecast
from smart_retail.analytics.results import AnalyticsRun
from smart_retail.domain import (
    ActorRole,
    ApprovalRequest,
    AuditActor,
    Device,
    DeviceEvent,
    DeviceEventRecord,
    InventoryAdjustment,
    InventorySnapshot,
    OperationAuditEvent,
    PriceChange,
    PriceRecord,
    Sku,
    Store,
    WorkOrder,
    WorkOrderRequest,
)
from smart_retail.knowledge.models import KnowledgeChunk, KnowledgeSearchResult, KnowledgeSource


class RepositoryError(RuntimeError):
    """Base class for persistence errors safe to translate at the API boundary."""


class ResourceAlreadyExistsError(RepositoryError):
    """Raised when a store or SKU identifier already exists."""


class ResourceNotFoundError(RepositoryError):
    """Raised when a referenced store or SKU does not exist."""


class IdempotencyConflictError(RepositoryError):
    """Raised when a request ID is reused with a different payload."""


class RetailRepository(Protocol):
    """Operations required by the current API use cases."""

    def create_store(self, store: Store, *, actor: AuditActor | None = None) -> Store: ...

    def create_sku(self, sku: Sku, *, actor: AuditActor | None = None) -> Sku: ...

    def create_device(self, device: Device, *, actor: AuditActor | None = None) -> Device: ...

    def get_device(self, device_id: str) -> Device | None: ...

    def record_device_event(
        self, event: DeviceEvent, *, actor: AuditActor | None = None
    ) -> DeviceEventRecord: ...

    def list_device_events(self, device_id: str, limit: int) -> list[DeviceEventRecord]: ...

    def get_inventory(self, store_id: str, sku: str) -> InventorySnapshot | None: ...

    def adjust_inventory(
        self, adjustment: InventoryAdjustment, *, actor: AuditActor | None = None
    ) -> InventorySnapshot: ...

    def set_price(self, change: PriceChange) -> PriceRecord: ...

    def get_price(self, store_id: str, sku: str) -> PriceRecord | None: ...

    def create_work_order(self, request: WorkOrderRequest) -> WorkOrder: ...

    def get_work_order(self, ticket_id: str) -> WorkOrder | None: ...

    def list_operation_audit_events(
        self,
        *,
        actor_id: str | None,
        resource_type: str | None,
        resource_id: str | None,
        limit: int,
    ) -> list[OperationAuditEvent]: ...

    def create_approval(self, approval: ApprovalRequest) -> ApprovalRequest: ...

    def get_approval(self, approval_id: str) -> ApprovalRequest | None: ...

    def decide_approval(
        self,
        approval_id: str,
        *,
        approved: bool,
        actor_id: str,
        actor_role: ActorRole,
    ) -> ApprovalRequest: ...

    def claim_approval_execution(self, approval_id: str) -> ApprovalRequest: ...

    def complete_approval_execution(
        self,
        approval_id: str,
        *,
        result: dict[str, object] | None,
        error: str | None,
    ) -> ApprovalRequest: ...

    def save_analytics_run(
        self,
        run: AnalyticsRun,
        anomalies: Sequence[InventoryAnomalyResult],
        forecasts: Sequence[DemandForecast],
    ) -> AnalyticsRun: ...

    def get_analytics_run(self, run_id: str) -> AnalyticsRun | None: ...

    def list_inventory_anomalies(
        self,
        run_id: str,
        *,
        store_id: str | None,
        sku: str | None,
        limit: int,
    ) -> list[InventoryAnomalyResult]: ...

    def list_demand_forecasts(
        self,
        run_id: str,
        *,
        store_id: str | None,
        sku: str | None,
        limit: int,
    ) -> list[DemandForecast]: ...

    def ingest_knowledge_source(
        self,
        source: KnowledgeSource,
        chunks: Sequence[KnowledgeChunk],
    ) -> KnowledgeSource: ...

    def search_knowledge(
        self,
        query_embedding: Sequence[float],
        *,
        source_ids: Sequence[str] | None,
        limit: int,
    ) -> list[KnowledgeSearchResult]: ...
