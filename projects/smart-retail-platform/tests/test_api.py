import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from smart_retail.analytics.batch import build_inventory_intelligence_batch
from smart_retail.analytics.data_quality import load_daily_metrics
from smart_retail.api.app import create_app
from smart_retail.copilot.agent import AgentSession, AgentTurn
from smart_retail.copilot.models import GeneratedCopilotAnswer
from smart_retail.copilot.tools import (
    ToolDefinition,
    ToolExecutionResult,
    ToolGateway,
    ToolInvocation,
)
from smart_retail.domain import ActorRole, InventoryAdjustment, Sku, Store
from smart_retail.knowledge.embedding import HashingEmbeddingProvider
from smart_retail.knowledge.ingestion import ingest_knowledge_manifest
from smart_retail.knowledge.models import KnowledgeSearchResult
from smart_retail.repositories.memory import InMemoryRetailRepository
from smart_retail.security import ApiKeyAuthenticator, Principal

EVALUATION_DATASET = (
    Path(__file__).parents[1] / "data" / "evaluation" / "inventory_anomalies_v1.csv"
)
KNOWLEDGE_MANIFEST = Path(__file__).parents[1] / "data" / "knowledge" / "manifest.json"
ADMIN_API_KEY = "test-admin-secret"
ADMIN_AUTHENTICATOR = ApiKeyAuthenticator(
    {ADMIN_API_KEY: Principal("test-admin", ActorRole.ADMIN)}
)


class _ApiAgentSession:
    def next_turn(self, tool_results: Sequence[ToolExecutionResult]) -> AgentTurn:
        if not tool_results:
            return AgentTurn(
                tool_calls=(
                    ToolInvocation(
                        call_id="api-inventory-call",
                        name="get_inventory",
                        arguments={"store_id": "store-1", "sku": "sku-1"},
                    ),
                )
            )
        result = tool_results[0]
        if result.output is None:
            raise AssertionError("inventory tool should return output")
        return AgentTurn(
            answer=GeneratedCopilotAnswer(
                answer=f"Inventory is {result.output['quantity']} units.",
                citations=[result.citation],
                insufficient_evidence=False,
            )
        )


class _ApiAgentModel:
    name = "api_trace_test_agent"

    def start(
        self,
        question: str,
        context: Sequence[KnowledgeSearchResult],
        tools: Sequence[ToolDefinition],
        *,
        requester: str,
    ) -> AgentSession:
        del question, context, tools, requester
        return _ApiAgentSession()


def client() -> TestClient:
    return TestClient(
        create_app(
            InMemoryRetailRepository(),
            authenticator=ADMIN_AUTHENTICATOR,
        ),
        headers={"X-API-Key": ADMIN_API_KEY},
    )


def seed_catalog(test_client: TestClient) -> None:
    assert test_client.post(
        "/stores", json={"store_id": "store-1", "name": "Chicago Loop"}
    ).status_code == 201
    assert test_client.post(
        "/skus", json={"sku": "sku-1", "name": "Milk"}
    ).status_code == 201


def seed_device(test_client: TestClient) -> None:
    seed_catalog(test_client)
    assert test_client.post(
        "/devices",
        json={
            "device_id": "sensor-1",
            "store_id": "store-1",
            "device_type": "temperature_sensor",
            "display_name": "Dairy sensor",
        },
    ).status_code == 201


def test_health_exposes_storage_mode() -> None:
    response = client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "storage": "InMemoryRetailRepository"}


def test_direct_write_requires_authenticated_actor() -> None:
    test_client = TestClient(create_app(InMemoryRetailRepository()))

    response = test_client.post(
        "/stores",
        json={"store_id": "store-1", "name": "Chicago Loop"},
    )

    assert response.status_code == 401


def test_catalog_write_rejects_operator_role() -> None:
    authenticator = ApiKeyAuthenticator(
        {"operator-secret": Principal("operator-1", ActorRole.OPERATOR)}
    )
    test_client = TestClient(
        create_app(InMemoryRetailRepository(), authenticator=authenticator),
        headers={"X-API-Key": "operator-secret"},
    )

    response = test_client.post(
        "/stores",
        json={"store_id": "store-1", "name": "Chicago Loop"},
    )

    assert response.status_code == 403


def test_authenticated_write_is_queryable_in_admin_audit_log() -> None:
    test_client = client()
    created = test_client.post(
        "/stores",
        json={"store_id": "store-audit-1", "name": "Audit Store"},
    )

    response = test_client.get(
        "/audit-events",
        params={"resource_type": "store", "resource_id": "store-audit-1"},
    )

    assert created.status_code == 201
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["actor_id"] == "test-admin"
    assert response.json()[0]["actor_role"] == "admin"


def test_request_observability_returns_trace_id_and_structured_log(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="smart_retail.http"):
        response = client().get("/health", headers={"X-Request-ID": "trace-eval-1"})

    event = json.loads(caplog.records[-1].message)
    assert response.headers["X-Request-ID"] == "trace-eval-1"
    assert event["event"] == "http_request_completed"
    assert event["request_id"] == "trace-eval-1"
    assert event["status_code"] == 200
    assert event["latency_ms"] >= 0


def test_inventory_adjustment_round_trip_and_idempotency() -> None:
    test_client = client()
    seed_catalog(test_client)
    payload = {
        "request_id": "delivery-2026-08-11-001",
        "store_id": "store-1",
        "sku": "sku-1",
        "quantity_delta": 12,
        "reason": "morning delivery",
    }

    first = test_client.post("/inventory/adjustments", json=payload)
    replay = test_client.post("/inventory/adjustments", json=payload)
    fetched = test_client.get("/inventory/store-1/sku-1")
    audit = test_client.get(
        "/audit-events",
        params={"resource_type": "inventory", "resource_id": "store-1/sku-1"},
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json() == replay.json()
    assert fetched.json()["quantity"] == 12
    assert len(audit.json()) == 1
    assert audit.json()[0]["request_id"] == "delivery-2026-08-11-001"


def test_negative_inventory_returns_conflict() -> None:
    test_client = client()
    seed_catalog(test_client)

    response = test_client.post(
        "/inventory/adjustments",
        json={
            "request_id": "sale-1",
            "store_id": "store-1",
            "sku": "sku-1",
            "quantity_delta": -1,
            "reason": "sale",
        },
    )

    assert response.status_code == 409
    assert "below zero" in response.json()["detail"]


def test_reused_request_id_with_different_payload_returns_conflict() -> None:
    test_client = client()
    seed_catalog(test_client)
    payload = {
        "request_id": "delivery-1",
        "store_id": "store-1",
        "sku": "sku-1",
        "quantity_delta": 5,
        "reason": "delivery",
    }
    assert test_client.post("/inventory/adjustments", json=payload).status_code == 200

    payload["quantity_delta"] = 6
    response = test_client.post("/inventory/adjustments", json=payload)

    assert response.status_code == 409
    assert "request_id" in response.json()["detail"]


def test_device_registration_and_lookup() -> None:
    test_client = client()
    seed_device(test_client)

    response = test_client.get("/devices/sensor-1")

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert response.json()["device_type"] == "temperature_sensor"


def test_device_requires_known_store() -> None:
    response = client().post(
        "/devices",
        json={
            "device_id": "sensor-1",
            "store_id": "missing-store",
            "device_type": "temperature_sensor",
            "display_name": "Dairy sensor",
        },
    )

    assert response.status_code == 404
    assert "store" in response.json()["detail"]


def test_device_event_round_trip_and_idempotency() -> None:
    test_client = client()
    seed_device(test_client)
    payload = {
        "event_id": "event-1",
        "device_id": "sensor-1",
        "event_type": "temperature_reading",
        "observed_at": "2026-08-11T10:00:00Z",
        "payload": {"temperature_c": 3.2, "battery_percent": 91},
    }

    first = test_client.post("/device-events", json=payload)
    replay = test_client.post("/device-events", json=payload)
    listed = test_client.get("/devices/sensor-1/events")

    assert first.status_code == 201
    assert replay.status_code == 201
    assert first.json() == replay.json()
    assert listed.status_code == 200
    assert [event["event_id"] for event in listed.json()] == ["event-1"]


def test_device_event_id_conflict_returns_409() -> None:
    test_client = client()
    seed_device(test_client)
    payload = {
        "event_id": "event-1",
        "device_id": "sensor-1",
        "event_type": "temperature_reading",
        "observed_at": "2026-08-11T10:00:00Z",
        "payload": {"temperature_c": 3.2},
    }
    assert test_client.post("/device-events", json=payload).status_code == 201

    payload["payload"] = {"temperature_c": 8.0}
    response = test_client.post("/device-events", json=payload)

    assert response.status_code == 409
    assert "event_id" in response.json()["detail"]


def test_analytics_run_and_filtered_results_are_queryable() -> None:
    repository = InMemoryRetailRepository()
    records = load_daily_metrics(EVALUATION_DATASET).records
    batch = build_inventory_intelligence_batch(
        records,
        dataset_version="inventory_anomalies_v1",
        run_id="run-1",
        created_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
    )
    repository.save_analytics_run(batch.run, batch.anomalies, batch.forecasts)
    test_client = TestClient(create_app(repository))

    run = test_client.get("/analytics/runs/run-1")
    anomalies = test_client.get(
        "/analytics/runs/run-1/anomalies",
        params={"sku": "milk-1", "limit": 2},
    )
    forecasts = test_client.get(
        "/analytics/runs/run-1/forecasts",
        params={"sku": "cereal-1", "limit": 3},
    )

    assert run.status_code == 200
    assert run.json()["dataset_version"] == "inventory_anomalies_v1"
    assert anomalies.status_code == 200
    assert len(anomalies.json()) == 2
    assert all(result["is_anomaly"] for result in anomalies.json())
    assert forecasts.status_code == 200
    assert len(forecasts.json()) == 3
    assert all(result["sku"] == "cereal-1" for result in forecasts.json())


def test_unknown_analytics_run_returns_404() -> None:
    test_client = client()

    run = test_client.get("/analytics/runs/missing")
    results = test_client.get("/analytics/runs/missing/anomalies")

    assert run.status_code == 404
    assert results.status_code == 404


def test_knowledge_search_returns_citable_source_chunks() -> None:
    repository = InMemoryRetailRepository()
    embedder = HashingEmbeddingProvider()
    ingest_knowledge_manifest(repository, embedder, KNOWLEDGE_MANIFEST)
    test_client = TestClient(create_app(repository, embedder))

    response = test_client.post(
        "/knowledge/search",
        json={
            "query": "dairy temperature above 5 degrees",
            "source_ids": ["refrigeration-manual"],
            "limit": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()[0]["section"] == "High-temperature alarm"
    assert response.json()[0]["citation"].startswith("refrigeration-manual@v1#")


def test_copilot_answer_is_structured_and_grounded() -> None:
    repository = InMemoryRetailRepository()
    embedder = HashingEmbeddingProvider()
    ingest_knowledge_manifest(repository, embedder, KNOWLEDGE_MANIFEST)
    test_client = TestClient(create_app(repository, embedder))

    response = test_client.post(
        "/copilot/ask",
        json={
            "question": "verified product above 5 degrees 15 minutes work order",
            "source_ids": ["refrigeration-manual"],
        },
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "extractive_fallback_v1"
    assert response.json()["citations"][0]["section"] == "High-temperature alarm"
    assert not response.json()["insufficient_evidence"]


def test_live_agent_reports_missing_provider_configuration(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    authenticator = ApiKeyAuthenticator(
        {"operator-secret": Principal("operator-1", ActorRole.OPERATOR)}
    )
    test_client = TestClient(
        create_app(InMemoryRetailRepository(), authenticator=authenticator)
    )
    unauthenticated = test_client.post(
        "/copilot/agent",
        json={"question": "Check inventory"},
    )
    response = test_client.post(
        "/copilot/agent",
        json={"question": "Check inventory"},
        headers={"X-API-Key": "operator-secret"},
    )

    assert unauthenticated.status_code == 401
    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_agent_api_correlates_http_tool_and_completion_logs(caplog) -> None:
    repository = InMemoryRetailRepository()
    repository.create_store(Store("store-1", "Chicago Loop"))
    repository.create_sku(Sku("sku-1", "Milk"))
    repository.adjust_inventory(
        InventoryAdjustment("seed-agent-api", "store-1", "sku-1", 12, "seed")
    )
    authenticator = ApiKeyAuthenticator(
        {"operator-secret": Principal("operator-1", ActorRole.OPERATOR)}
    )
    test_client = TestClient(
        create_app(
            repository,
            agent_model=_ApiAgentModel(),
            authenticator=authenticator,
        )
    )

    with caplog.at_level(logging.INFO):
        response = test_client.post(
            "/copilot/agent",
            json={"question": "What is the current inventory?"},
            headers={
                "X-API-Key": "operator-secret",
                "X-Request-ID": "trace-api-agent-1",
            },
        )

    assert response.status_code == 200
    assert response.json()["answer"]["answer"] == "Inventory is 12 units."
    events = [json.loads(record.message) for record in caplog.records if record.message[0] == "{"]
    correlated = [
        event
        for event in events
        if event.get("event")
        in {
            "copilot_tool_completed",
            "copilot_agent_completed",
            "http_request_completed",
        }
    ]
    assert {event["request_id"] for event in correlated} == {"trace-api-agent-1"}
    assert {event["event"] for event in correlated} == {
        "copilot_tool_completed",
        "copilot_agent_completed",
        "http_request_completed",
    }


def test_high_risk_approval_enforces_role_then_executes() -> None:
    repository = InMemoryRetailRepository()
    repository.create_store(Store("store-1", "Chicago Loop"))
    repository.create_sku(Sku("sku-1", "Milk"))
    pending = ToolGateway(repository).execute(
        ToolInvocation(
            call_id="call-price",
            name="set_price",
            arguments={
                "request_id": "price-1",
                "store_id": "store-1",
                "sku": "sku-1",
                "new_price": "3.49",
                "reason": "approved promotion",
            },
        )
    )
    assert pending.approval_id is not None
    authenticator = ApiKeyAuthenticator(
        {
            "operator-secret": Principal("operator-1", ActorRole.OPERATOR),
            "pricing-secret": Principal("pricing-lead-1", ActorRole.PRICING_LEAD),
        }
    )
    test_client = TestClient(create_app(repository, authenticator=authenticator))

    unauthenticated = test_client.post(
        f"/approvals/{pending.approval_id}/decision",
        json={"approved": True},
    )

    forbidden = test_client.post(
        f"/approvals/{pending.approval_id}/decision",
        json={"approved": True},
        headers={"X-API-Key": "operator-secret"},
    )
    approved = test_client.post(
        f"/approvals/{pending.approval_id}/decision",
        json={"approved": True},
        headers={"X-API-Key": "pricing-secret"},
    )

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403
    assert approved.status_code == 200
    assert approved.json()["status"] == "executed"
    assert approved.json()["decided_by"] == "pricing-lead-1"
    assert approved.json()["decided_role"] == "pricing_lead"
    assert approved.json()["result"]["amount"] == "3.49"
