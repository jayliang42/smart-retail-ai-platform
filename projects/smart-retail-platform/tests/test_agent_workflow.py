import json
import logging
from collections.abc import Sequence
from decimal import Decimal

import pytest

from smart_retail.api.schemas import AgentRunResponse
from smart_retail.copilot.agent import (
    AgentModel,
    AgentModelUnavailableError,
    AgentRunner,
    AgentSession,
    AgentStepLimitError,
    AgentTurn,
    ModelCostRates,
    ModelUsage,
    TransientAgentError,
)
from smart_retail.copilot.models import GeneratedCopilotAnswer
from smart_retail.copilot.tools import ToolDefinition, ToolExecutionResult, ToolInvocation
from smart_retail.domain import ApprovalStatus, InventoryAdjustment, Sku, Store
from smart_retail.knowledge.embedding import HashingEmbeddingProvider
from smart_retail.knowledge.models import KnowledgeSearchResult
from smart_retail.observability import bind_request_id, reset_request_id
from smart_retail.repositories.memory import InMemoryRetailRepository


class _InventorySession:
    def next_turn(self, tool_results: Sequence[ToolExecutionResult]) -> AgentTurn:
        if not tool_results:
            return AgentTurn(
                tool_calls=(
                    ToolInvocation(
                        call_id="inventory-call",
                        name="get_inventory",
                        arguments={"store_id": "store-1", "sku": "sku-1"},
                    ),
                )
            )
        quantity = tool_results[0].output["quantity"] if tool_results[0].output else None
        return AgentTurn(
            answer=GeneratedCopilotAnswer(
                answer=f"Current inventory is {quantity} units.",
                citations=[tool_results[0].citation],
                insufficient_evidence=False,
            )
        )


class _InventoryModel:
    name = "scripted_inventory_agent"

    def start(
        self,
        question: str,
        context: Sequence[KnowledgeSearchResult],
        tools: Sequence[ToolDefinition],
        *,
        requester: str,
    ) -> AgentSession:
        del question, context, tools, requester
        return _InventorySession()


class _HighRiskSession:
    def next_turn(self, tool_results: Sequence[ToolExecutionResult]) -> AgentTurn:
        if not tool_results:
            return AgentTurn(
                tool_calls=(
                    ToolInvocation(
                        call_id="adjust-call",
                        name="adjust_inventory",
                        arguments={
                            "request_id": "agent-adjust-1",
                            "store_id": "store-1",
                            "sku": "sku-1",
                            "quantity_delta": -2,
                            "reason": "cycle count correction",
                        },
                    ),
                )
            )
        return AgentTurn(
            answer=GeneratedCopilotAnswer(
                answer="The inventory adjustment is awaiting manager approval.",
                citations=[tool_results[0].citation],
                insufficient_evidence=False,
            )
        )


class _HighRiskModel(_InventoryModel):
    name = "scripted_high_risk_agent"

    def start(
        self,
        question: str,
        context: Sequence[KnowledgeSearchResult],
        tools: Sequence[ToolDefinition],
        *,
        requester: str,
    ) -> AgentSession:
        del question, context, tools, requester
        return _HighRiskSession()


class _NeverFinishesSession:
    def __init__(self) -> None:
        self._step = 0

    def next_turn(self, tool_results: Sequence[ToolExecutionResult]) -> AgentTurn:
        del tool_results
        self._step += 1
        return AgentTurn(
            tool_calls=(
                ToolInvocation(
                    call_id=f"loop-{self._step}",
                    name="get_inventory",
                    arguments={"store_id": "store-1", "sku": "sku-1"},
                ),
            )
        )


class _NeverFinishesModel(_InventoryModel):
    name = "non_terminating_test_agent"

    def start(
        self,
        question: str,
        context: Sequence[KnowledgeSearchResult],
        tools: Sequence[ToolDefinition],
        *,
        requester: str,
    ) -> AgentSession:
        del question, context, tools, requester
        return _NeverFinishesSession()


class _FlakySession:
    def __init__(self, failures: int) -> None:
        self._failures_remaining = failures
        self.calls = 0

    def next_turn(self, tool_results: Sequence[ToolExecutionResult]) -> AgentTurn:
        del tool_results
        self.calls += 1
        if self._failures_remaining:
            self._failures_remaining -= 1
            raise TransientAgentError("temporary provider outage")
        return AgentTurn(
            answer=GeneratedCopilotAnswer(
                answer="There is not enough evidence to answer.",
                citations=[],
                insufficient_evidence=True,
            )
        )


class _FlakyModel(_InventoryModel):
    name = "flaky_test_agent"

    def __init__(self, failures: int) -> None:
        self.session = _FlakySession(failures)

    def start(
        self,
        question: str,
        context: Sequence[KnowledgeSearchResult],
        tools: Sequence[ToolDefinition],
        *,
        requester: str,
    ) -> AgentSession:
        del question, context, tools, requester
        return self.session


class _MeteredSession:
    def next_turn(self, tool_results: Sequence[ToolExecutionResult]) -> AgentTurn:
        del tool_results
        return AgentTurn(
            answer=GeneratedCopilotAnswer(
                answer="There is not enough evidence to answer.",
                citations=[],
                insufficient_evidence=True,
            ),
            usage=ModelUsage(input_tokens=1_000, output_tokens=500),
        )


class _MeteredModel(_InventoryModel):
    name = "metered_test_agent"

    def start(
        self,
        question: str,
        context: Sequence[KnowledgeSearchResult],
        tools: Sequence[ToolDefinition],
        *,
        requester: str,
    ) -> AgentSession:
        del question, context, tools, requester
        return _MeteredSession()


def configured_repository() -> InMemoryRetailRepository:
    repository = InMemoryRetailRepository()
    repository.create_store(Store("store-1", "Chicago Loop"))
    repository.create_sku(Sku("sku-1", "Milk"))
    repository.adjust_inventory(
        InventoryAdjustment("seed", "store-1", "sku-1", 12, "seed")
    )
    return repository


def runner(model: AgentModel, *, maximum_steps: int = 6) -> AgentRunner:
    return AgentRunner(
        configured_repository(),
        HashingEmbeddingProvider(),
        model,
        maximum_steps=maximum_steps,
    )


def test_agent_calls_inventory_tool_then_cites_the_result() -> None:
    result = runner(_InventoryModel()).run(
        "What is inventory for store-1 sku-1?",
        requester="operator-1",
    )

    assert result.answer.answer == "Current inventory is 12 units."
    assert result.answer.citations[0].kind == "tool"
    assert result.answer.citations[0].citation == "tool:get_inventory#inventory-call"
    assert result.steps == 2
    response = AgentRunResponse.model_validate(result)
    assert response.telemetry.provider_attempts == 2
    assert response.telemetry.tool_calls == 1


def test_agent_high_risk_tool_creates_pending_approval_without_mutation() -> None:
    repository = configured_repository()
    workflow = AgentRunner(repository, HashingEmbeddingProvider(), _HighRiskModel())

    result = workflow.run("Reduce inventory by two", requester="operator-1")

    assert result.tool_results[0].approval_id is not None
    approval = repository.get_approval(result.tool_results[0].approval_id)
    assert approval is not None and approval.status is ApprovalStatus.PENDING
    inventory = repository.get_inventory("store-1", "sku-1")
    assert inventory is not None and inventory.quantity == 12


def test_agent_stops_after_bounded_number_of_steps() -> None:
    with pytest.raises(AgentStepLimitError, match="maximum_steps=2"):
        runner(_NeverFinishesModel(), maximum_steps=2).run(
            "Keep checking inventory",
            requester="operator-1",
        )


def test_agent_retries_transient_model_failure_then_recovers() -> None:
    model = _FlakyModel(failures=1)
    delays: list[float] = []
    workflow = AgentRunner(
        configured_repository(),
        HashingEmbeddingProvider(),
        model,
        model_retry_delays=(0.1, 0.2),
        sleep=delays.append,
    )

    result = workflow.run("Unknown question", requester="operator-1")

    assert result.answer.insufficient_evidence is True
    assert model.session.calls == 2
    assert delays == [0.1]


def test_agent_reports_unavailable_after_bounded_retries() -> None:
    model = _FlakyModel(failures=3)
    workflow = AgentRunner(
        configured_repository(),
        HashingEmbeddingProvider(),
        model,
        model_retry_delays=(0.1, 0.2),
        sleep=lambda _: None,
    )

    with pytest.raises(AgentModelUnavailableError, match="after 3 attempts"):
        workflow.run("Unknown question", requester="operator-1")

    assert model.session.calls == 3


def test_agent_records_tokens_latency_and_configured_cost() -> None:
    clock = iter([10.0, 10.125])
    workflow = AgentRunner(
        configured_repository(),
        HashingEmbeddingProvider(),
        _MeteredModel(),
        monotonic=lambda: next(clock),
        cost_rates=ModelCostRates(Decimal("2.00"), Decimal("8.00")),
    )

    result = workflow.run("Unknown question", requester="operator-1")

    assert result.telemetry.provider_attempts == 1
    assert result.telemetry.input_tokens == 1_000
    assert result.telemetry.output_tokens == 500
    assert result.telemetry.latency_ms == 125.0
    assert result.telemetry.estimated_cost_usd == Decimal("0.006000")


def test_agent_logs_share_request_id_across_tool_and_completion(caplog) -> None:
    request_id_token = bind_request_id("trace-agent-1")
    try:
        with caplog.at_level(logging.INFO, logger="smart_retail.copilot.agent"):
            runner(_InventoryModel()).run(
                "What is inventory?",
                requester="operator-1",
            )
    finally:
        reset_request_id(request_id_token)

    events = [json.loads(record.message) for record in caplog.records]
    traced = [
        event
        for event in events
        if event["event"] in {"copilot_tool_completed", "copilot_agent_completed"}
    ]
    assert [event["event"] for event in traced] == [
        "copilot_tool_completed",
        "copilot_agent_completed",
    ]
    assert {event["request_id"] for event in traced} == {"trace-agent-1"}
