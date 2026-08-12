"""Thread-safe in-memory repository used for fast tests and local exploration."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from math import sqrt
from threading import RLock

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
    WorkOrderStatus,
)
from smart_retail.knowledge.models import KnowledgeChunk, KnowledgeSearchResult, KnowledgeSource
from smart_retail.repositories.base import (
    IdempotencyConflictError,
    ResourceAlreadyExistsError,
    ResourceNotFoundError,
)


@dataclass(frozen=True, slots=True)
class _ProcessedAdjustment:
    adjustment: InventoryAdjustment
    snapshot: InventorySnapshot


@dataclass(frozen=True, slots=True)
class _ProcessedDeviceEvent:
    event: DeviceEvent
    record: DeviceEventRecord


@dataclass(frozen=True, slots=True)
class _ProcessedPriceChange:
    change: PriceChange
    record: PriceRecord


@dataclass(frozen=True, slots=True)
class _ProcessedWorkOrder:
    request: WorkOrderRequest
    work_order: WorkOrder


class InMemoryRetailRepository:
    """A deterministic repository with the same behavior expected from PostgreSQL."""

    def __init__(self) -> None:
        self._stores: dict[str, Store] = {}
        self._skus: dict[str, Sku] = {}
        self._devices: dict[str, Device] = {}
        self._device_events: dict[str, _ProcessedDeviceEvent] = {}
        self._inventory: dict[tuple[str, str], InventorySnapshot] = {}
        self._processed: dict[str, _ProcessedAdjustment] = {}
        self._analytics_runs: dict[str, AnalyticsRun] = {}
        self._analytics_anomalies: dict[
            tuple[str, str, str, date], InventoryAnomalyResult
        ] = {}
        self._analytics_forecasts: dict[tuple[str, str, str, date], DemandForecast] = {}
        self._knowledge_sources: dict[tuple[str, str], KnowledgeSource] = {}
        self._knowledge_chunks: dict[str, KnowledgeChunk] = {}
        self._prices: dict[tuple[str, str], PriceRecord] = {}
        self._price_changes: dict[str, _ProcessedPriceChange] = {}
        self._work_orders: dict[str, _ProcessedWorkOrder] = {}
        self._approvals: dict[str, ApprovalRequest] = {}
        self._operation_audit_events: list[OperationAuditEvent] = []
        self._lock = RLock()

    def create_store(self, store: Store, *, actor: AuditActor | None = None) -> Store:
        with self._lock:
            if store.store_id in self._stores:
                raise ResourceAlreadyExistsError(f"store already exists: {store.store_id}")
            self._stores[store.store_id] = store
            self._audit(actor, "create", "store", store.store_id)
            return store

    def create_sku(self, sku: Sku, *, actor: AuditActor | None = None) -> Sku:
        with self._lock:
            if sku.sku in self._skus:
                raise ResourceAlreadyExistsError(f"SKU already exists: {sku.sku}")
            self._skus[sku.sku] = sku
            self._audit(actor, "create", "sku", sku.sku)
            return sku

    def create_device(self, device: Device, *, actor: AuditActor | None = None) -> Device:
        with self._lock:
            if device.store_id not in self._stores:
                raise ResourceNotFoundError(f"store not found: {device.store_id}")
            if device.device_id in self._devices:
                raise ResourceAlreadyExistsError(f"device already exists: {device.device_id}")
            self._devices[device.device_id] = device
            self._audit(actor, "create", "device", device.device_id)
            return device

    def get_device(self, device_id: str) -> Device | None:
        with self._lock:
            return self._devices.get(device_id)

    def record_device_event(
        self,
        event: DeviceEvent,
        *,
        actor: AuditActor | None = None,
    ) -> DeviceEventRecord:
        with self._lock:
            processed = self._device_events.get(event.event_id)
            if processed is not None:
                if processed.event != event:
                    raise IdempotencyConflictError(
                        f"event_id already used with another payload: {event.event_id}"
                    )
                return processed.record
            if event.device_id not in self._devices:
                raise ResourceNotFoundError(f"device not found: {event.device_id}")

            record = DeviceEventRecord(
                event_id=event.event_id,
                device_id=event.device_id,
                event_type=event.event_type,
                observed_at=event.observed_at,
                received_at=datetime.now(UTC),
                payload=event.payload,
            )
            self._device_events[event.event_id] = _ProcessedDeviceEvent(event, record)
            self._audit(
                actor,
                "record",
                "device_event",
                event.event_id,
                request_id=event.event_id,
            )
            return record

    def list_device_events(self, device_id: str, limit: int) -> list[DeviceEventRecord]:
        with self._lock:
            if device_id not in self._devices:
                raise ResourceNotFoundError(f"device not found: {device_id}")
            records = [
                processed.record
                for processed in self._device_events.values()
                if processed.event.device_id == device_id
            ]
            records.sort(key=lambda record: (record.observed_at, record.event_id), reverse=True)
            return records[:limit]

    def get_inventory(self, store_id: str, sku: str) -> InventorySnapshot | None:
        with self._lock:
            return self._inventory.get((store_id, sku))

    def adjust_inventory(
        self,
        adjustment: InventoryAdjustment,
        *,
        actor: AuditActor | None = None,
    ) -> InventorySnapshot:
        with self._lock:
            processed = self._processed.get(adjustment.request_id)
            if processed is not None:
                if processed.adjustment != adjustment:
                    raise IdempotencyConflictError(
                        f"request_id already used with another payload: {adjustment.request_id}"
                    )
                return processed.snapshot

            if adjustment.store_id not in self._stores:
                raise ResourceNotFoundError(f"store not found: {adjustment.store_id}")
            if adjustment.sku not in self._skus:
                raise ResourceNotFoundError(f"SKU not found: {adjustment.sku}")

            key = (adjustment.store_id, adjustment.sku)
            current = self._inventory.get(key)
            new_quantity = adjustment.apply(current.quantity if current else 0)
            snapshot = InventorySnapshot(
                store_id=adjustment.store_id,
                sku=adjustment.sku,
                quantity=new_quantity,
                updated_at=datetime.now(UTC),
            )
            self._inventory[key] = snapshot
            self._processed[adjustment.request_id] = _ProcessedAdjustment(adjustment, snapshot)
            self._audit(
                actor,
                "adjust",
                "inventory",
                f"{adjustment.store_id}/{adjustment.sku}",
                request_id=adjustment.request_id,
            )
            return snapshot

    def set_price(self, change: PriceChange) -> PriceRecord:
        with self._lock:
            processed = self._price_changes.get(change.request_id)
            if processed is not None:
                if processed.change != change:
                    raise IdempotencyConflictError(
                        f"request_id already used with another price payload: {change.request_id}"
                    )
                return processed.record
            if change.store_id not in self._stores:
                raise ResourceNotFoundError(f"store not found: {change.store_id}")
            if change.sku not in self._skus:
                raise ResourceNotFoundError(f"SKU not found: {change.sku}")
            record = PriceRecord(
                store_id=change.store_id,
                sku=change.sku,
                amount=change.new_price,
                currency=change.currency,
                updated_at=datetime.now(UTC),
            )
            self._prices[(change.store_id, change.sku)] = record
            self._price_changes[change.request_id] = _ProcessedPriceChange(change, record)
            return record

    def get_price(self, store_id: str, sku: str) -> PriceRecord | None:
        with self._lock:
            return self._prices.get((store_id, sku))

    def create_work_order(self, request: WorkOrderRequest) -> WorkOrder:
        with self._lock:
            processed = self._work_orders.get(request.request_id)
            if processed is not None:
                if processed.request != request:
                    raise IdempotencyConflictError(
                        "request_id already used with another work-order payload: "
                        f"{request.request_id}"
                    )
                return processed.work_order
            if request.store_id not in self._stores:
                raise ResourceNotFoundError(f"store not found: {request.store_id}")
            work_order = WorkOrder(
                ticket_id=request.request_id,
                store_id=request.store_id,
                category=request.category,
                priority=request.priority,
                status=WorkOrderStatus.OPEN,
                summary=request.summary,
            )
            self._work_orders[request.request_id] = _ProcessedWorkOrder(request, work_order)
            return work_order

    def get_work_order(self, ticket_id: str) -> WorkOrder | None:
        with self._lock:
            processed = self._work_orders.get(ticket_id)
            return processed.work_order if processed else None

    def create_approval(self, approval: ApprovalRequest) -> ApprovalRequest:
        with self._lock:
            existing = self._approvals.get(approval.approval_id)
            if existing is not None:
                if (
                    existing.tool_name != approval.tool_name
                    or existing.arguments != approval.arguments
                ):
                    raise ResourceAlreadyExistsError(
                        f"approval already exists with another payload: {approval.approval_id}"
                    )
                return existing
            self._approvals[approval.approval_id] = approval
            return approval

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        with self._lock:
            return self._approvals.get(approval_id)

    def decide_approval(
        self,
        approval_id: str,
        *,
        approved: bool,
        actor_id: str,
        actor_role: ActorRole,
    ) -> ApprovalRequest:
        with self._lock:
            approval = self._require_approval(approval_id)
            decided = approval.decide(
                approved=approved,
                actor_id=actor_id,
                actor_role=actor_role,
            )
            self._approvals[approval_id] = decided
            return decided

    def claim_approval_execution(self, approval_id: str) -> ApprovalRequest:
        with self._lock:
            claimed = self._require_approval(approval_id).claim_execution()
            self._approvals[approval_id] = claimed
            return claimed

    def complete_approval_execution(
        self,
        approval_id: str,
        *,
        result: dict[str, object] | None,
        error: str | None,
    ) -> ApprovalRequest:
        with self._lock:
            completed = self._require_approval(approval_id).complete(
                result=result,
                error=error,
            )
            self._approvals[approval_id] = completed
            return completed

    def _require_approval(self, approval_id: str) -> ApprovalRequest:
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise ResourceNotFoundError(f"approval not found: {approval_id}")
        return approval

    def list_operation_audit_events(
        self,
        *,
        actor_id: str | None,
        resource_type: str | None,
        resource_id: str | None,
        limit: int,
    ) -> list[OperationAuditEvent]:
        with self._lock:
            events = [
                event
                for event in self._operation_audit_events
                if (actor_id is None or event.actor.actor_id == actor_id)
                and (resource_type is None or event.resource_type == resource_type)
                and (resource_id is None or event.resource_id == resource_id)
            ]
            events.sort(key=lambda event: (event.occurred_at, event.event_id), reverse=True)
            return events[:limit]

    def _audit(
        self,
        actor: AuditActor | None,
        action: str,
        resource_type: str,
        resource_id: str,
        *,
        request_id: str | None = None,
    ) -> None:
        if actor is None:
            return
        self._operation_audit_events.append(
            OperationAuditEvent(
                actor=actor,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                request_id=request_id,
            )
        )

    def save_analytics_run(
        self,
        run: AnalyticsRun,
        anomalies: Sequence[InventoryAnomalyResult],
        forecasts: Sequence[DemandForecast],
    ) -> AnalyticsRun:
        with self._lock:
            if run.run_id in self._analytics_runs:
                raise ResourceAlreadyExistsError(f"analytics run already exists: {run.run_id}")
            self._analytics_runs[run.run_id] = run
            for anomaly in anomalies:
                key = (run.run_id, anomaly.store_id, anomaly.sku, anomaly.business_date)
                self._analytics_anomalies[key] = anomaly
            for forecast in forecasts:
                key = (run.run_id, forecast.store_id, forecast.sku, forecast.target_date)
                self._analytics_forecasts[key] = forecast
            return run

    def get_analytics_run(self, run_id: str) -> AnalyticsRun | None:
        with self._lock:
            return self._analytics_runs.get(run_id)

    def list_inventory_anomalies(
        self,
        run_id: str,
        *,
        store_id: str | None,
        sku: str | None,
        limit: int,
    ) -> list[InventoryAnomalyResult]:
        with self._lock:
            self._require_analytics_run(run_id)
            results = [
                result
                for key, result in self._analytics_anomalies.items()
                if key[0] == run_id
                and (store_id is None or result.store_id == store_id)
                and (sku is None or result.sku == sku)
            ]
            results.sort(
                key=lambda item: (item.business_date, item.store_id, item.sku),
                reverse=True,
            )
            return results[:limit]

    def list_demand_forecasts(
        self,
        run_id: str,
        *,
        store_id: str | None,
        sku: str | None,
        limit: int,
    ) -> list[DemandForecast]:
        with self._lock:
            self._require_analytics_run(run_id)
            results = [
                result
                for key, result in self._analytics_forecasts.items()
                if key[0] == run_id
                and (store_id is None or result.store_id == store_id)
                and (sku is None or result.sku == sku)
            ]
            results.sort(key=lambda item: (item.target_date, item.store_id, item.sku), reverse=True)
            return results[:limit]

    def _require_analytics_run(self, run_id: str) -> None:
        if run_id not in self._analytics_runs:
            raise ResourceNotFoundError(f"analytics run not found: {run_id}")

    def ingest_knowledge_source(
        self,
        source: KnowledgeSource,
        chunks: Sequence[KnowledgeChunk],
    ) -> KnowledgeSource:
        with self._lock:
            key = (source.source_id, source.source_version)
            existing = self._knowledge_sources.get(key)
            if existing is not None:
                if existing.checksum != source.checksum:
                    raise ResourceAlreadyExistsError(
                        "knowledge source version already exists with different content: "
                        f"{source.source_id}@{source.source_version}"
                    )
                return existing
            for chunk in chunks:
                if (chunk.source_id, chunk.source_version) != key:
                    raise ValueError("knowledge chunk does not belong to its source version")
                if chunk.chunk_id in self._knowledge_chunks:
                    raise ResourceAlreadyExistsError(
                        f"knowledge chunk already exists: {chunk.chunk_id}"
                    )
            self._knowledge_sources[key] = source
            self._knowledge_chunks.update((chunk.chunk_id, chunk) for chunk in chunks)
            return source

    def search_knowledge(
        self,
        query_embedding: Sequence[float],
        *,
        source_ids: Sequence[str] | None,
        limit: int,
    ) -> list[KnowledgeSearchResult]:
        with self._lock:
            allowed_sources = set(source_ids) if source_ids is not None else None
            results = [
                KnowledgeSearchResult(
                    chunk_id=chunk.chunk_id,
                    source_id=chunk.source_id,
                    source_version=chunk.source_version,
                    title=chunk.title,
                    section=chunk.section,
                    content=chunk.content,
                    score=_cosine_similarity(query_embedding, chunk.embedding),
                )
                for chunk in self._knowledge_chunks.values()
                if allowed_sources is None or chunk.source_id in allowed_sources
            ]
            results.sort(key=lambda result: (-result.score, result.citation))
            return results[:limit]


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions do not match")
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
