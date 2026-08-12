from collections.abc import Sequence
from pathlib import Path

import pytest

from smart_retail.copilot.agent import AgentSession, AgentTurn
from smart_retail.copilot.live_evaluation import (
    LiveAgentCase,
    evaluate_live_agent,
    load_live_agent_cases,
)
from smart_retail.copilot.models import GeneratedCopilotAnswer
from smart_retail.copilot.tools import (
    ToolDefinition,
    ToolExecutionResult,
    ToolInvocation,
    ToolStatus,
)
from smart_retail.knowledge.models import KnowledgeSearchResult

PROJECT_ROOT = Path(__file__).parents[1]
LIVE_DATASET = PROJECT_ROOT / "data" / "evaluation" / "copilot_live_agent_v1.jsonl"
KNOWLEDGE_MANIFEST = PROJECT_ROOT / "data" / "knowledge" / "manifest.json"


class _InventorySession:
    def next_turn(self, tool_results: Sequence[ToolExecutionResult]) -> AgentTurn:
        if not tool_results:
            return AgentTurn(
                tool_calls=(
                    ToolInvocation(
                        call_id="live-eval-test-call",
                        name="get_inventory",
                        arguments={"store_id": "store-1", "sku": "sku-1"},
                    ),
                )
            )
        return AgentTurn(
            answer=GeneratedCopilotAnswer(
                answer="Inventory was retrieved.",
                citations=[tool_results[0].citation],
                insufficient_evidence=False,
            )
        )


class _InventoryModel:
    name = "scripted_live_eval_test"

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


def test_live_agent_dataset_has_valid_unique_cases() -> None:
    cases = load_live_agent_cases(LIVE_DATASET)

    assert len(cases) == 12
    assert len({case.case_id for case in cases}) == 12
    assert sum(case.expected_approval_required for case in cases) == 2
    assert sum(bool(case.required_knowledge_sections) for case in cases) == 4


def test_live_agent_dataset_rejects_mismatched_tool_and_status_lengths(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "invalid.jsonl"
    dataset.write_text(
        '{"case_id":"invalid","question":"test","expected_tools":["get_price"],'
        '"expected_statuses":[],"expected_approval_required":false}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="equal lengths"):
        load_live_agent_cases(dataset)


def test_live_agent_evaluator_scores_tool_status_and_approval() -> None:
    case = LiveAgentCase(
        case_id="scripted-1",
        question="Get inventory",
        expected_tools=["get_inventory"],
        expected_statuses=[ToolStatus.SUCCESS],
        expected_approval_required=False,
    )

    result = evaluate_live_agent(
        [case],
        KNOWLEDGE_MANIFEST,
        _InventoryModel(),
        dataset_version="scripted_test_v1",
    )

    assert result.passed_cases == 1
    assert result.pass_rate == 1.0
    assert result.tool_sequence_accuracy == 1.0
    assert result.status_sequence_accuracy == 1.0
    assert result.approval_accuracy == 1.0
    assert result.cases[0].actual_tools == ("get_inventory",)
