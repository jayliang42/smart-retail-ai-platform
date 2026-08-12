"""SQLAlchemy/PostgreSQL implementation of the retail repository."""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    create_engine,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from smart_retail.analytics.anomalies import InventoryAnomalyResult
from smart_retail.analytics.forecasting import DemandForecast
from smart_retail.analytics.results import AnalyticsRun
from smart_retail.domain import (
    ActorRole,
    ApprovalRequest,
    ApprovalStatus,
    AuditActor,
    Device,
    DeviceEvent,
    DeviceEventRecord,
    DeviceStatus,
    DeviceType,
    InventoryAdjustment,
    InventorySnapshot,
    OperationAuditEvent,
    PriceChange,
    PriceRecord,
    Sku,
    Store,
    WorkOrder,
    WorkOrderPriority,
    WorkOrderRequest,
    WorkOrderStatus,
)
from smart_retail.knowledge.embedding import EMBEDDING_DIMENSIONS
from smart_retail.knowledge.models import KnowledgeChunk, KnowledgeSearchResult, KnowledgeSource
from smart_retail.repositories.base import (
    IdempotencyConflictError,
    ResourceAlreadyExistsError,
    ResourceNotFoundError,
)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy mappings."""


class StoreRow(Base):
    __tablename__ = "stores"

    store_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))


class SkuRow(Base):
    __tablename__ = "skus"

    sku: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))


class InventoryRow(Base):
    __tablename__ = "inventory"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_inventory_quantity_non_negative"),
    )

    store_id: Mapped[str] = mapped_column(
        ForeignKey("stores.store_id"), primary_key=True
    )
    sku: Mapped[str] = mapped_column(ForeignKey("skus.sku"), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InventoryAdjustmentRow(Base):
    __tablename__ = "inventory_adjustments"
    __table_args__ = (
        CheckConstraint(
            "quantity_delta <> 0", name="ck_inventory_adjustments_delta_non_zero"
        ),
        CheckConstraint(
            "resulting_quantity >= 0",
            name="ck_inventory_adjustments_result_non_negative",
        ),
    )

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.store_id"), index=True)
    sku: Mapped[str] = mapped_column(ForeignKey("skus.sku"), index=True)
    quantity_delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500))
    resulting_quantity: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PriceRow(Base):
    __tablename__ = "prices"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_prices_amount_positive"),
    )

    store_id: Mapped[str] = mapped_column(
        ForeignKey("stores.store_id"), primary_key=True
    )
    sku: Mapped[str] = mapped_column(ForeignKey("skus.sku"), primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PriceChangeRow(Base):
    __tablename__ = "price_changes"
    __table_args__ = (
        CheckConstraint("new_price > 0", name="ck_price_changes_new_price_positive"),
    )

    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.store_id"), index=True)
    sku: Mapped[str] = mapped_column(ForeignKey("skus.sku"), index=True)
    new_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkOrderRow(Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'critical')",
            name="ck_work_orders_priority_valid",
        ),
        CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved')",
            name="ck_work_orders_status_valid",
        ),
    )

    ticket_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.store_id"), index=True)
    category: Mapped[str] = mapped_column(String(100))
    priority: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApprovalRequestRow(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'executing', 'executed', 'failed')",
            name="ck_approval_requests_status_valid",
        ),
        CheckConstraint(
            "decided_role IS NULL OR decided_role IN "
            "('operator', 'manager', 'pricing_lead', 'admin')",
            name="ck_approval_requests_role_valid",
        ),
    )

    approval_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(100), index=True)
    call_id: Mapped[str] = mapped_column(String(128))
    arguments: Mapped[dict[str, object]] = mapped_column(JSONB)
    requester: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(128))
    decided_role: Mapped[str | None] = mapped_column(String(30))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class OperationAuditEventRow(Base):
    __tablename__ = "operation_audit_events"
    __table_args__ = (
        CheckConstraint(
            "actor_role IN ('operator', 'manager', 'pricing_lead', 'admin')",
            name="ck_operation_audit_events_role_valid",
        ),
        Index(
            "ix_operation_audit_resource_occurred",
            "resource_type",
            "resource_id",
            "occurred_at",
        ),
        Index("ix_operation_audit_actor_occurred", "actor_id", "occurred_at"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(128))
    actor_role: Mapped[str] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(50))
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str] = mapped_column(String(300))
    request_id: Mapped[str | None] = mapped_column(String(128))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeviceRow(Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint(
            "device_type IN ('refrigeration_unit', 'temperature_sensor', 'pos_terminal', "
            "'camera', 'edge_gateway', 'other')",
            name="ck_devices_type_valid",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'maintenance')",
            name="ck_devices_status_valid",
        ),
    )

    device_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.store_id"), index=True)
    device_type: Mapped[str] = mapped_column(String(40))
    display_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeviceEventRow(Base):
    __tablename__ = "device_events"
    __table_args__ = (
        Index("ix_device_events_device_observed_at", "device_id", "observed_at"),
    )

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.device_id"), index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)


class AnalyticsRunRow(Base):
    __tablename__ = "analytics_runs"
    __table_args__ = (
        CheckConstraint("input_rows >= 0", name="ck_analytics_runs_input_rows_non_negative"),
    )

    run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    dataset_version: Mapped[str] = mapped_column(String(128))
    input_rows: Mapped[int] = mapped_column(Integer)
    anomaly_detector: Mapped[str] = mapped_column(String(200))
    forecaster: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class InventoryAnomalyRow(Base):
    __tablename__ = "inventory_anomalies"
    __table_args__ = (
        Index(
            "ix_inventory_anomalies_run_store_sku_date",
            "run_id",
            "store_id",
            "sku",
            "business_date",
        ),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("analytics_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    store_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_anomaly: Mapped[bool] = mapped_column(Boolean)
    reasons: Mapped[list[str]] = mapped_column(JSONB)
    trailing_demand: Mapped[float | None] = mapped_column(Float)


class DemandForecastRow(Base):
    __tablename__ = "demand_forecasts"
    __table_args__ = (
        CheckConstraint(
            "predicted_units >= 0", name="ck_demand_forecasts_prediction_non_negative"
        ),
        CheckConstraint(
            "observed_units >= 0", name="ck_demand_forecasts_observed_non_negative"
        ),
        CheckConstraint("history_size > 0", name="ck_demand_forecasts_history_positive"),
        Index(
            "ix_demand_forecasts_run_store_sku_date",
            "run_id",
            "store_id",
            "sku",
            "target_date",
        ),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("analytics_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    store_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), primary_key=True)
    target_date: Mapped[date] = mapped_column(Date, primary_key=True)
    predicted_units: Mapped[float] = mapped_column(Float)
    observed_units: Mapped[int] = mapped_column(Integer)
    history_size: Mapped[int] = mapped_column(Integer)


class KnowledgeSourceRow(Base):
    __tablename__ = "knowledge_sources"

    source_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    source_uri: Mapped[str] = mapped_column(String(500))
    checksum: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KnowledgeChunkRow(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "source_version"],
            ["knowledge_sources.source_id", "knowledge_sources.source_version"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_knowledge_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "ix_knowledge_chunks_source_version_ordinal",
            "source_id",
            "source_version",
            "ordinal",
        ),
    )

    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(128))
    source_version: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    section: Mapped[str] = mapped_column(String(300))
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))


def normalize_database_url(database_url: str) -> str:
    """Select the installed psycopg v3 driver for provider-style PostgreSQL URLs."""

    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _acquire_transaction_lock(session: Session, lock_key: str) -> None:
    session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0)))
    )


def build_session_factory(database_url: str) -> sessionmaker[Session]:
    """Create database sessions; schema changes are owned by Alembic migrations."""

    engine = create_engine(normalize_database_url(database_url), pool_pre_ping=True)
    return sessionmaker(engine, expire_on_commit=False)


class PostgresRetailRepository:
    """PostgreSQL repository using short transactions and row-level locking."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def create_store(self, store: Store, *, actor: AuditActor | None = None) -> Store:
        with self._sessions() as session:
            session.add(StoreRow(store_id=store.store_id, name=store.name))
            _add_audit_event(session, actor, "create", "store", store.store_id)
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise ResourceAlreadyExistsError(
                    f"store already exists: {store.store_id}"
                ) from error
        return store

    def create_sku(self, sku: Sku, *, actor: AuditActor | None = None) -> Sku:
        with self._sessions() as session:
            session.add(SkuRow(sku=sku.sku, name=sku.name))
            _add_audit_event(session, actor, "create", "sku", sku.sku)
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise ResourceAlreadyExistsError(f"SKU already exists: {sku.sku}") from error
        return sku

    def create_device(self, device: Device, *, actor: AuditActor | None = None) -> Device:
        with self._sessions() as session:
            if session.get(StoreRow, device.store_id) is None:
                raise ResourceNotFoundError(f"store not found: {device.store_id}")
            session.add(
                DeviceRow(
                    device_id=device.device_id,
                    store_id=device.store_id,
                    device_type=device.device_type.value,
                    display_name=device.display_name,
                    status=device.status.value,
                    registered_at=device.registered_at,
                )
            )
            _add_audit_event(session, actor, "create", "device", device.device_id)
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise ResourceAlreadyExistsError(
                    f"device already exists: {device.device_id}"
                ) from error
        return device

    def get_device(self, device_id: str) -> Device | None:
        with self._sessions() as session:
            row = session.get(DeviceRow, device_id)
            return _device(row) if row else None

    def record_device_event(
        self,
        event: DeviceEvent,
        *,
        actor: AuditActor | None = None,
    ) -> DeviceEventRecord:
        with self._sessions() as session, session.begin():
            processed = session.get(DeviceEventRow, event.event_id)
            if processed is not None:
                if not _same_device_event(processed, event):
                    raise IdempotencyConflictError(
                        f"event_id already used with another payload: {event.event_id}"
                    )
                return _device_event_record(processed)
            if session.get(DeviceRow, event.device_id) is None:
                raise ResourceNotFoundError(f"device not found: {event.device_id}")

            now = datetime.now(UTC)
            row = DeviceEventRow(
                event_id=event.event_id,
                device_id=event.device_id,
                event_type=event.event_type,
                observed_at=event.observed_at,
                received_at=now,
                payload=dict(event.payload),
            )
            session.add(row)
            _add_audit_event(
                session,
                actor,
                "record",
                "device_event",
                event.event_id,
                request_id=event.event_id,
            )
            return _device_event_record(row)

    def list_device_events(self, device_id: str, limit: int) -> list[DeviceEventRecord]:
        with self._sessions() as session:
            if session.get(DeviceRow, device_id) is None:
                raise ResourceNotFoundError(f"device not found: {device_id}")
            query = (
                select(DeviceEventRow)
                .where(DeviceEventRow.device_id == device_id)
                .order_by(DeviceEventRow.observed_at.desc(), DeviceEventRow.event_id.desc())
                .limit(limit)
            )
            return [_device_event_record(row) for row in session.scalars(query)]

    def get_inventory(self, store_id: str, sku: str) -> InventorySnapshot | None:
        with self._sessions() as session:
            row = session.get(InventoryRow, (store_id, sku))
            return _snapshot(row) if row else None

    def adjust_inventory(
        self,
        adjustment: InventoryAdjustment,
        *,
        actor: AuditActor | None = None,
    ) -> InventorySnapshot:
        with self._sessions() as session, session.begin():
            # A row lock cannot protect the first adjustment because no inventory row exists yet.
            # The transaction-scoped advisory lock serializes both first creation and idempotent
            # retries for one store/SKU key, then releases automatically at commit or rollback.
            inventory_lock_key = f"inventory:{adjustment.store_id}:{adjustment.sku}"
            _acquire_transaction_lock(session, inventory_lock_key)
            processed = session.get(InventoryAdjustmentRow, adjustment.request_id)
            if processed is not None:
                if not _same_adjustment(processed, adjustment):
                    raise IdempotencyConflictError(
                        f"request_id already used with another payload: {adjustment.request_id}"
                    )
                return InventorySnapshot(
                    store_id=processed.store_id,
                    sku=processed.sku,
                    quantity=processed.resulting_quantity,
                    updated_at=processed.created_at,
                )

            if session.get(StoreRow, adjustment.store_id) is None:
                raise ResourceNotFoundError(f"store not found: {adjustment.store_id}")
            if session.get(SkuRow, adjustment.sku) is None:
                raise ResourceNotFoundError(f"SKU not found: {adjustment.sku}")

            query = (
                select(InventoryRow)
                .where(
                    InventoryRow.store_id == adjustment.store_id,
                    InventoryRow.sku == adjustment.sku,
                )
                .with_for_update()
            )
            row = session.scalar(query)
            current_quantity = row.quantity if row else 0
            new_quantity = adjustment.apply(current_quantity)
            now = datetime.now(UTC)
            if row is None:
                row = InventoryRow(
                    store_id=adjustment.store_id,
                    sku=adjustment.sku,
                    quantity=new_quantity,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.quantity = new_quantity
                row.updated_at = now

            session.add(
                InventoryAdjustmentRow(
                    request_id=adjustment.request_id,
                    store_id=adjustment.store_id,
                    sku=adjustment.sku,
                    quantity_delta=adjustment.quantity_delta,
                    reason=adjustment.reason,
                    resulting_quantity=new_quantity,
                    created_at=now,
                )
            )
            _add_audit_event(
                session,
                actor,
                "adjust",
                "inventory",
                f"{adjustment.store_id}/{adjustment.sku}",
                request_id=adjustment.request_id,
            )
            return InventorySnapshot(
                store_id=adjustment.store_id,
                sku=adjustment.sku,
                quantity=new_quantity,
                updated_at=now,
            )

    def set_price(self, change: PriceChange) -> PriceRecord:
        with self._sessions() as session, session.begin():
            price_lock_key = f"price:{change.store_id}:{change.sku}"
            _acquire_transaction_lock(session, price_lock_key)
            processed = session.get(PriceChangeRow, change.request_id)
            if processed is not None:
                if not _same_price_change(processed, change):
                    raise IdempotencyConflictError(
                        f"request_id already used with another price payload: {change.request_id}"
                    )
                return PriceRecord(
                    store_id=processed.store_id,
                    sku=processed.sku,
                    amount=processed.new_price,
                    currency=processed.currency,
                    updated_at=processed.created_at,
                )
            if session.get(StoreRow, change.store_id) is None:
                raise ResourceNotFoundError(f"store not found: {change.store_id}")
            if session.get(SkuRow, change.sku) is None:
                raise ResourceNotFoundError(f"SKU not found: {change.sku}")

            now = datetime.now(UTC)
            row = session.get(PriceRow, (change.store_id, change.sku))
            if row is None:
                row = PriceRow(
                    store_id=change.store_id,
                    sku=change.sku,
                    amount=change.new_price,
                    currency=change.currency,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.amount = change.new_price
                row.currency = change.currency
                row.updated_at = now
            session.add(
                PriceChangeRow(
                    request_id=change.request_id,
                    store_id=change.store_id,
                    sku=change.sku,
                    new_price=change.new_price,
                    currency=change.currency,
                    reason=change.reason,
                    created_at=now,
                )
            )
            return PriceRecord(
                store_id=change.store_id,
                sku=change.sku,
                amount=change.new_price,
                currency=change.currency,
                updated_at=now,
            )

    def get_price(self, store_id: str, sku: str) -> PriceRecord | None:
        with self._sessions() as session:
            row = session.get(PriceRow, (store_id, sku))
            return _price_record(row) if row else None

    def create_work_order(self, request: WorkOrderRequest) -> WorkOrder:
        with self._sessions() as session, session.begin():
            row = session.get(WorkOrderRow, request.request_id)
            if row is not None:
                if not _same_work_order_request(row, request):
                    raise IdempotencyConflictError(
                        "request_id already used with another work-order payload: "
                        f"{request.request_id}"
                    )
                return _work_order(row)
            if session.get(StoreRow, request.store_id) is None:
                raise ResourceNotFoundError(f"store not found: {request.store_id}")
            row = WorkOrderRow(
                ticket_id=request.request_id,
                store_id=request.store_id,
                category=request.category,
                priority=request.priority.value,
                status=WorkOrderStatus.OPEN.value,
                summary=request.summary,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            return _work_order(row)

    def get_work_order(self, ticket_id: str) -> WorkOrder | None:
        with self._sessions() as session:
            row = session.get(WorkOrderRow, ticket_id)
            return _work_order(row) if row else None

    def list_operation_audit_events(
        self,
        *,
        actor_id: str | None,
        resource_type: str | None,
        resource_id: str | None,
        limit: int,
    ) -> list[OperationAuditEvent]:
        with self._sessions() as session:
            query = select(OperationAuditEventRow)
            if actor_id is not None:
                query = query.where(OperationAuditEventRow.actor_id == actor_id)
            if resource_type is not None:
                query = query.where(OperationAuditEventRow.resource_type == resource_type)
            if resource_id is not None:
                query = query.where(OperationAuditEventRow.resource_id == resource_id)
            query = query.order_by(
                OperationAuditEventRow.occurred_at.desc(),
                OperationAuditEventRow.event_id.desc(),
            ).limit(limit)
            return [_operation_audit_event(row) for row in session.scalars(query)]

    def create_approval(self, approval: ApprovalRequest) -> ApprovalRequest:
        with self._sessions() as session:
            existing = session.get(ApprovalRequestRow, approval.approval_id)
            if existing is not None:
                if (
                    existing.tool_name != approval.tool_name
                    or existing.arguments != dict(approval.arguments)
                ):
                    raise ResourceAlreadyExistsError(
                        f"approval already exists with another payload: {approval.approval_id}"
                    )
                return _approval_request(existing)
            session.add(
                ApprovalRequestRow(
                    approval_id=approval.approval_id,
                    tool_name=approval.tool_name,
                    call_id=approval.call_id,
                    arguments=dict(approval.arguments),
                    requester=approval.requester,
                    reason=approval.reason,
                    status=approval.status.value,
                    created_at=approval.created_at,
                    decided_by=None,
                    decided_role=None,
                    decided_at=None,
                    result=None,
                    error=None,
                )
            )
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise ResourceAlreadyExistsError(
                    f"approval already exists: {approval.approval_id}"
                ) from error
        return approval

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        with self._sessions() as session:
            row = session.get(ApprovalRequestRow, approval_id)
            return _approval_request(row) if row else None

    def decide_approval(
        self,
        approval_id: str,
        *,
        approved: bool,
        actor_id: str,
        actor_role: ActorRole,
    ) -> ApprovalRequest:
        with self._sessions() as session, session.begin():
            row = _locked_approval(session, approval_id)
            decided = _approval_request(row).decide(
                approved=approved,
                actor_id=actor_id,
                actor_role=actor_role,
            )
            _update_approval_row(row, decided)
            return decided

    def claim_approval_execution(self, approval_id: str) -> ApprovalRequest:
        with self._sessions() as session, session.begin():
            row = _locked_approval(session, approval_id)
            claimed = _approval_request(row).claim_execution()
            _update_approval_row(row, claimed)
            return claimed

    def complete_approval_execution(
        self,
        approval_id: str,
        *,
        result: dict[str, object] | None,
        error: str | None,
    ) -> ApprovalRequest:
        with self._sessions() as session, session.begin():
            row = _locked_approval(session, approval_id)
            completed = _approval_request(row).complete(result=result, error=error)
            _update_approval_row(row, completed)
            return completed

    def save_analytics_run(
        self,
        run: AnalyticsRun,
        anomalies: Sequence[InventoryAnomalyResult],
        forecasts: Sequence[DemandForecast],
    ) -> AnalyticsRun:
        with self._sessions() as session:
            if session.get(AnalyticsRunRow, run.run_id) is not None:
                raise ResourceAlreadyExistsError(f"analytics run already exists: {run.run_id}")
            session.add(
                AnalyticsRunRow(
                    run_id=run.run_id,
                    dataset_version=run.dataset_version,
                    input_rows=run.input_rows,
                    anomaly_detector=run.anomaly_detector,
                    forecaster=run.forecaster,
                    created_at=run.created_at,
                )
            )
            session.add_all(
                InventoryAnomalyRow(
                    run_id=run.run_id,
                    store_id=result.store_id,
                    sku=result.sku,
                    business_date=result.business_date,
                    is_anomaly=result.is_anomaly,
                    reasons=list(result.reasons),
                    trailing_demand=result.trailing_demand,
                )
                for result in anomalies
            )
            session.add_all(
                DemandForecastRow(
                    run_id=run.run_id,
                    store_id=result.store_id,
                    sku=result.sku,
                    target_date=result.target_date,
                    predicted_units=result.predicted_units,
                    observed_units=result.observed_units,
                    history_size=result.history_size,
                )
                for result in forecasts
            )
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise ResourceAlreadyExistsError(
                    f"analytics run or result already exists: {run.run_id}"
                ) from error
        return run

    def get_analytics_run(self, run_id: str) -> AnalyticsRun | None:
        with self._sessions() as session:
            row = session.get(AnalyticsRunRow, run_id)
            return _analytics_run(row) if row else None

    def list_inventory_anomalies(
        self,
        run_id: str,
        *,
        store_id: str | None,
        sku: str | None,
        limit: int,
    ) -> list[InventoryAnomalyResult]:
        with self._sessions() as session:
            _require_analytics_run(session, run_id)
            query = select(InventoryAnomalyRow).where(InventoryAnomalyRow.run_id == run_id)
            if store_id is not None:
                query = query.where(InventoryAnomalyRow.store_id == store_id)
            if sku is not None:
                query = query.where(InventoryAnomalyRow.sku == sku)
            query = query.order_by(
                InventoryAnomalyRow.business_date.desc(),
                InventoryAnomalyRow.store_id,
                InventoryAnomalyRow.sku,
            ).limit(limit)
            return [_inventory_anomaly(row) for row in session.scalars(query)]

    def list_demand_forecasts(
        self,
        run_id: str,
        *,
        store_id: str | None,
        sku: str | None,
        limit: int,
    ) -> list[DemandForecast]:
        with self._sessions() as session:
            _require_analytics_run(session, run_id)
            query = select(DemandForecastRow).where(DemandForecastRow.run_id == run_id)
            if store_id is not None:
                query = query.where(DemandForecastRow.store_id == store_id)
            if sku is not None:
                query = query.where(DemandForecastRow.sku == sku)
            query = query.order_by(
                DemandForecastRow.target_date.desc(),
                DemandForecastRow.store_id,
                DemandForecastRow.sku,
            ).limit(limit)
            return [_demand_forecast(row) for row in session.scalars(query)]

    def ingest_knowledge_source(
        self,
        source: KnowledgeSource,
        chunks: Sequence[KnowledgeChunk],
    ) -> KnowledgeSource:
        key = (source.source_id, source.source_version)
        for chunk in chunks:
            if (chunk.source_id, chunk.source_version) != key:
                raise ValueError("knowledge chunk does not belong to its source version")
            if len(chunk.embedding) != EMBEDDING_DIMENSIONS:
                raise ValueError(
                    f"knowledge embedding must have {EMBEDDING_DIMENSIONS} dimensions"
                )

        with self._sessions() as session:
            existing = session.get(KnowledgeSourceRow, key)
            if existing is not None:
                if existing.checksum != source.checksum:
                    raise ResourceAlreadyExistsError(
                        "knowledge source version already exists with different content: "
                        f"{source.source_id}@{source.source_version}"
                    )
                return _knowledge_source(existing)

            session.add(
                KnowledgeSourceRow(
                    source_id=source.source_id,
                    source_version=source.source_version,
                    title=source.title,
                    source_uri=source.source_uri,
                    checksum=source.checksum,
                    content=source.content,
                    created_at=datetime.now(UTC),
                )
            )
            session.flush()
            session.add_all(
                KnowledgeChunkRow(
                    chunk_id=chunk.chunk_id,
                    source_id=chunk.source_id,
                    source_version=chunk.source_version,
                    title=chunk.title,
                    section=chunk.section,
                    ordinal=chunk.ordinal,
                    content=chunk.content,
                    embedding=list(chunk.embedding),
                )
                for chunk in chunks
            )
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise ResourceAlreadyExistsError(
                    f"knowledge source or chunk already exists: {source.source_id}"
                ) from error
        return source

    def search_knowledge(
        self,
        query_embedding: Sequence[float],
        *,
        source_ids: Sequence[str] | None,
        limit: int,
    ) -> list[KnowledgeSearchResult]:
        if len(query_embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError(f"query embedding must have {EMBEDDING_DIMENSIONS} dimensions")
        distance = KnowledgeChunkRow.embedding.cosine_distance(list(query_embedding))
        query = select(KnowledgeChunkRow, distance.label("distance"))
        if source_ids is not None:
            query = query.where(KnowledgeChunkRow.source_id.in_(source_ids))
        query = query.order_by(distance).limit(limit)

        with self._sessions() as session:
            return [
                _knowledge_search_result(row, 1.0 - float(distance_value))
                for row, distance_value in session.execute(query)
            ]


def _snapshot(row: InventoryRow) -> InventorySnapshot:
    return InventorySnapshot(
        store_id=row.store_id,
        sku=row.sku,
        quantity=row.quantity,
        updated_at=row.updated_at,
    )


def _same_adjustment(row: InventoryAdjustmentRow, adjustment: InventoryAdjustment) -> bool:
    return (
        row.store_id == adjustment.store_id
        and row.sku == adjustment.sku
        and row.quantity_delta == adjustment.quantity_delta
        and row.reason == adjustment.reason
    )


def _same_price_change(row: PriceChangeRow, change: PriceChange) -> bool:
    return (
        row.store_id == change.store_id
        and row.sku == change.sku
        and row.new_price == change.new_price
        and row.currency == change.currency
        and row.reason == change.reason
    )


def _price_record(row: PriceRow) -> PriceRecord:
    return PriceRecord(
        store_id=row.store_id,
        sku=row.sku,
        amount=row.amount,
        currency=row.currency,
        updated_at=row.updated_at,
    )


def _same_work_order_request(row: WorkOrderRow, request: WorkOrderRequest) -> bool:
    return (
        row.store_id == request.store_id
        and row.category == request.category
        and row.priority == request.priority.value
        and row.summary == request.summary
    )


def _work_order(row: WorkOrderRow) -> WorkOrder:
    return WorkOrder(
        ticket_id=row.ticket_id,
        store_id=row.store_id,
        category=row.category,
        priority=WorkOrderPriority(row.priority),
        status=WorkOrderStatus(row.status),
        summary=row.summary,
        created_at=row.created_at,
    )


def _locked_approval(session: Session, approval_id: str) -> ApprovalRequestRow:
    query = (
        select(ApprovalRequestRow)
        .where(ApprovalRequestRow.approval_id == approval_id)
        .with_for_update()
    )
    row = session.scalar(query)
    if row is None:
        raise ResourceNotFoundError(f"approval not found: {approval_id}")
    return row


def _add_audit_event(
    session: Session,
    actor: AuditActor | None,
    action: str,
    resource_type: str,
    resource_id: str,
    *,
    request_id: str | None = None,
) -> None:
    if actor is None:
        return
    event = OperationAuditEvent(
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
    )
    session.add(
        OperationAuditEventRow(
            event_id=event.event_id,
            actor_id=event.actor.actor_id,
            actor_role=event.actor.role.value,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            request_id=event.request_id,
            occurred_at=event.occurred_at,
        )
    )


def _operation_audit_event(row: OperationAuditEventRow) -> OperationAuditEvent:
    return OperationAuditEvent(
        event_id=row.event_id,
        actor=AuditActor(actor_id=row.actor_id, role=ActorRole(row.actor_role)),
        action=row.action,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        request_id=row.request_id,
        occurred_at=row.occurred_at,
    )


def _approval_request(row: ApprovalRequestRow) -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=row.approval_id,
        tool_name=row.tool_name,
        call_id=row.call_id,
        arguments=row.arguments,
        requester=row.requester,
        reason=row.reason,
        status=ApprovalStatus(row.status),
        created_at=row.created_at,
        decided_by=row.decided_by,
        decided_role=ActorRole(row.decided_role) if row.decided_role else None,
        decided_at=row.decided_at,
        result=row.result,
        error=row.error,
    )


def _update_approval_row(row: ApprovalRequestRow, approval: ApprovalRequest) -> None:
    row.status = approval.status.value
    row.decided_by = approval.decided_by
    row.decided_role = approval.decided_role.value if approval.decided_role else None
    row.decided_at = approval.decided_at
    row.result = dict(approval.result) if approval.result is not None else None
    row.error = approval.error


def _device(row: DeviceRow) -> Device:
    return Device(
        device_id=row.device_id,
        store_id=row.store_id,
        device_type=DeviceType(row.device_type),
        display_name=row.display_name,
        status=DeviceStatus(row.status),
        registered_at=row.registered_at,
    )


def _device_event_record(row: DeviceEventRow) -> DeviceEventRecord:
    return DeviceEventRecord(
        event_id=row.event_id,
        device_id=row.device_id,
        event_type=row.event_type,
        observed_at=row.observed_at,
        received_at=row.received_at,
        payload=row.payload,
    )


def _same_device_event(row: DeviceEventRow, event: DeviceEvent) -> bool:
    return (
        row.device_id == event.device_id
        and row.event_type == event.event_type
        and row.observed_at == event.observed_at
        and row.payload == dict(event.payload)
    )


def _require_analytics_run(session: Session, run_id: str) -> None:
    if session.get(AnalyticsRunRow, run_id) is None:
        raise ResourceNotFoundError(f"analytics run not found: {run_id}")


def _analytics_run(row: AnalyticsRunRow) -> AnalyticsRun:
    return AnalyticsRun(
        run_id=row.run_id,
        dataset_version=row.dataset_version,
        input_rows=row.input_rows,
        anomaly_detector=row.anomaly_detector,
        forecaster=row.forecaster,
        created_at=row.created_at,
    )


def _inventory_anomaly(row: InventoryAnomalyRow) -> InventoryAnomalyResult:
    return InventoryAnomalyResult(
        store_id=row.store_id,
        sku=row.sku,
        business_date=row.business_date,
        is_anomaly=row.is_anomaly,
        reasons=tuple(row.reasons),
        trailing_demand=row.trailing_demand,
    )


def _demand_forecast(row: DemandForecastRow) -> DemandForecast:
    return DemandForecast(
        store_id=row.store_id,
        sku=row.sku,
        target_date=row.target_date,
        predicted_units=row.predicted_units,
        observed_units=row.observed_units,
        history_size=row.history_size,
    )


def _knowledge_source(row: KnowledgeSourceRow) -> KnowledgeSource:
    return KnowledgeSource(
        source_id=row.source_id,
        title=row.title,
        source_version=row.source_version,
        source_uri=row.source_uri,
        content=row.content,
    )


def _knowledge_search_result(
    row: KnowledgeChunkRow,
    score: float,
) -> KnowledgeSearchResult:
    return KnowledgeSearchResult(
        chunk_id=row.chunk_id,
        source_id=row.source_id,
        source_version=row.source_version,
        title=row.title,
        section=row.section,
        content=row.content,
        score=max(-1.0, min(1.0, score)),
    )
