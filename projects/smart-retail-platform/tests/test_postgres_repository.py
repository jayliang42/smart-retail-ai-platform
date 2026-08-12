"""PostgreSQL integration test; skipped unless TEST_DATABASE_URL is configured."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest

from smart_retail.analytics.batch import build_inventory_intelligence_batch
from smart_retail.analytics.data_quality import load_daily_metrics
from smart_retail.copilot.tools import ToolGateway, ToolInvocation, ToolStatus
from smart_retail.domain import (
    ActorRole,
    ApprovalStatus,
    AuditActor,
    Device,
    DeviceEvent,
    DeviceType,
    InventoryAdjustment,
    PriceChange,
    Sku,
    Store,
)
from smart_retail.knowledge.chunking import create_knowledge_chunks
from smart_retail.knowledge.embedding import HashingEmbeddingProvider
from smart_retail.knowledge.models import KnowledgeSource
from smart_retail.repositories.postgres import (
    PostgresRetailRepository,
    build_session_factory,
)

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
EVALUATION_DATASET = (
    Path(__file__).parents[1] / "data" / "evaluation" / "inventory_anomalies_v1.csv"
)

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL integration tests",
)


def test_postgres_adjustment_persists_and_is_idempotent() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:12]
    store_id = f"test-store-{suffix}"
    sku = f"test-sku-{suffix}"
    repository = PostgresRetailRepository(build_session_factory(DATABASE_URL))
    repository.create_store(Store(store_id, "Integration Test Store"))
    repository.create_sku(Sku(sku, "Integration Test SKU"))
    adjustment = InventoryAdjustment(
        request_id=f"test-request-{suffix}",
        store_id=store_id,
        sku=sku,
        quantity_delta=8,
        reason="integration test",
    )

    first = repository.adjust_inventory(adjustment)
    replay = repository.adjust_inventory(adjustment)
    fetched = repository.get_inventory(store_id, sku)

    assert first == replay
    assert fetched is not None
    assert fetched.quantity == 8


def test_postgres_concurrent_first_adjustments_do_not_lose_updates() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:12]
    store_id = f"test-store-{suffix}"
    sku = f"test-sku-{suffix}"
    repository = PostgresRetailRepository(build_session_factory(DATABASE_URL))
    repository.create_store(Store(store_id, "Concurrent Test Store"))
    repository.create_sku(Sku(sku, "Concurrent Test SKU"))
    barrier = Barrier(2)

    def adjust(request_id: str, quantity_delta: int) -> int:
        barrier.wait(timeout=5)
        result = repository.adjust_inventory(
            InventoryAdjustment(
                request_id=request_id,
                store_id=store_id,
                sku=sku,
                quantity_delta=quantity_delta,
                reason="concurrent integration test",
            )
        )
        return result.quantity

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(adjust, f"concurrent-a-{suffix}", 5),
            executor.submit(adjust, f"concurrent-b-{suffix}", 7),
        ]
        intermediate_quantities = [future.result(timeout=10) for future in futures]

    fetched = repository.get_inventory(store_id, sku)
    assert fetched is not None and fetched.quantity == 12
    assert sorted(intermediate_quantities) in ([5, 12], [7, 12])


def test_postgres_concurrent_same_request_is_applied_once() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:12]
    store_id = f"test-store-{suffix}"
    sku = f"test-sku-{suffix}"
    repository = PostgresRetailRepository(build_session_factory(DATABASE_URL))
    repository.create_store(Store(store_id, "Idempotency Race Store"))
    repository.create_sku(Sku(sku, "Idempotency Race SKU"))
    adjustment = InventoryAdjustment(
        request_id=f"same-request-{suffix}",
        store_id=store_id,
        sku=sku,
        quantity_delta=5,
        reason="concurrent idempotency test",
    )
    barrier = Barrier(2)

    def replay() -> int:
        barrier.wait(timeout=5)
        return repository.adjust_inventory(adjustment).quantity

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(replay), executor.submit(replay)]
        quantities = [future.result(timeout=10) for future in futures]

    fetched = repository.get_inventory(store_id, sku)
    assert quantities == [5, 5]
    assert fetched is not None and fetched.quantity == 5


def test_postgres_concurrent_first_price_changes_both_complete() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:12]
    store_id = f"test-store-{suffix}"
    sku = f"test-sku-{suffix}"
    repository = PostgresRetailRepository(build_session_factory(DATABASE_URL))
    repository.create_store(Store(store_id, "Concurrent Price Store"))
    repository.create_sku(Sku(sku, "Concurrent Price SKU"))
    barrier = Barrier(2)

    def change_price(request_id: str, amount: str) -> str:
        barrier.wait(timeout=5)
        record = repository.set_price(
            PriceChange(
                request_id=request_id,
                store_id=store_id,
                sku=sku,
                new_price=Decimal(amount),
                reason="concurrent price integration test",
            )
        )
        return str(record.amount)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(change_price, f"price-a-{suffix}", "3.49"),
            executor.submit(change_price, f"price-b-{suffix}", "3.99"),
        ]
        returned_prices = {future.result(timeout=10) for future in futures}

    fetched = repository.get_price(store_id, sku)
    assert returned_prices == {"3.49", "3.99"}
    assert fetched is not None and str(fetched.amount) in returned_prices


def test_postgres_device_event_persists_and_is_idempotent() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:12]
    store_id = f"test-store-{suffix}"
    device_id = f"test-device-{suffix}"
    repository = PostgresRetailRepository(build_session_factory(DATABASE_URL))
    repository.create_store(Store(store_id, "Integration Test Store"))
    repository.create_device(
        Device(
            device_id=device_id,
            store_id=store_id,
            device_type=DeviceType.TEMPERATURE_SENSOR,
            display_name="Integration Test Sensor",
        )
    )
    event = DeviceEvent(
        event_id=f"test-event-{suffix}",
        device_id=device_id,
        event_type="temperature_reading",
        observed_at=datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
        payload={"temperature_c": 3.2},
    )

    first = repository.record_device_event(event)
    replay = repository.record_device_event(event)
    listed = repository.list_device_events(device_id, limit=10)

    assert first == replay
    assert listed == [first]


def test_postgres_authenticated_write_persists_one_audit_event() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:12]
    store_id = f"test-audit-store-{suffix}"
    repository = PostgresRetailRepository(build_session_factory(DATABASE_URL))
    actor = AuditActor("integration-admin", ActorRole.ADMIN)

    repository.create_store(Store(store_id, "Audit Integration Store"), actor=actor)
    events = repository.list_operation_audit_events(
        actor_id=actor.actor_id,
        resource_type="store",
        resource_id=store_id,
        limit=10,
    )

    assert len(events) == 1
    assert events[0].actor == actor
    assert events[0].action == "create"


def test_postgres_analytics_batch_persists_and_filters_results() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:12]
    repository = PostgresRetailRepository(build_session_factory(DATABASE_URL))
    records = load_daily_metrics(EVALUATION_DATASET).records
    batch = build_inventory_intelligence_batch(
        records,
        dataset_version="inventory_anomalies_v1",
        run_id=f"test-analytics-{suffix}",
    )

    repository.save_analytics_run(batch.run, batch.anomalies, batch.forecasts)
    fetched = repository.get_analytics_run(batch.run.run_id)
    anomalies = repository.list_inventory_anomalies(
        batch.run.run_id,
        store_id="store-1",
        sku="milk-1",
        limit=100,
    )
    forecasts = repository.list_demand_forecasts(
        batch.run.run_id,
        store_id="store-1",
        sku="cereal-1",
        limit=100,
    )

    assert fetched == batch.run
    assert len(anomalies) == 5
    assert len(forecasts) == 12


def test_postgres_knowledge_source_is_idempotent_and_searchable() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:12]
    source_id = f"test-manual-{suffix}"
    repository = PostgresRetailRepository(build_session_factory(DATABASE_URL))
    embedder = HashingEmbeddingProvider()
    source = KnowledgeSource(
        source_id=source_id,
        title="Test refrigeration manual",
        source_version="v1",
        source_uri=f"test://{source_id}/v1",
        content=(
            "# Alarm\n\nIf verified temperature remains above 5 degrees for 15 minutes, "
            "move product and open a priority one work order."
        ),
    )
    chunks = create_knowledge_chunks(source, embedder)

    first = repository.ingest_knowledge_source(source, chunks)
    replay = repository.ingest_knowledge_source(source, chunks)
    query = embedder.embed_texts(["priority one temperature work order"])[0]
    results = repository.search_knowledge(query, source_ids=[source_id], limit=3)

    assert replay == first
    assert results
    assert results[0].source_id == source_id
    assert results[0].score > 0


def test_postgres_high_risk_approval_executes_price_change_once() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:12]
    store_id = f"test-store-{suffix}"
    sku = f"test-sku-{suffix}"
    repository = PostgresRetailRepository(build_session_factory(DATABASE_URL))
    repository.create_store(Store(store_id, "Approval Test Store"))
    repository.create_sku(Sku(sku, "Approval Test SKU"))
    gateway = ToolGateway(repository)
    pending = gateway.execute(
        ToolInvocation(
            call_id=f"price-call-{suffix}",
            name="set_price",
            arguments={
                "request_id": f"price-request-{suffix}",
                "store_id": store_id,
                "sku": sku,
                "new_price": "4.99",
                "reason": "integration test",
            },
        )
    )

    assert pending.status is ToolStatus.APPROVAL_REQUIRED
    assert pending.approval_id is not None
    assert repository.get_price(store_id, sku) is None

    executed = gateway.decide_and_execute(
        pending.approval_id,
        approved=True,
        actor_id="pricing-lead-integration",
        actor_role=ActorRole.PRICING_LEAD,
    )

    assert executed.status is ApprovalStatus.EXECUTED
    assert repository.get_approval(pending.approval_id) == executed
    price = repository.get_price(store_id, sku)
    assert price is not None and str(price.amount) == "4.99"
