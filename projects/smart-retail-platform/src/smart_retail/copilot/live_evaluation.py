"""Optional end-to-end Agent evaluation that requires a live model provider."""

import argparse
import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from smart_retail.copilot.agent import AgentModel, AgentRunner, ModelCostRates, OpenAIAgentModel
from smart_retail.copilot.tools import ToolStatus
from smart_retail.domain import (
    Device,
    DeviceType,
    InventoryAdjustment,
    PriceChange,
    Sku,
    Store,
)
from smart_retail.knowledge.embedding import HashingEmbeddingProvider
from smart_retail.knowledge.ingestion import ingest_knowledge_manifest
from smart_retail.repositories.memory import InMemoryRetailRepository


class LiveAgentCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    expected_tools: list[str]
    expected_statuses: list[ToolStatus]
    expected_approval_required: bool
    required_knowledge_sections: list[str] = Field(default_factory=list)

    def model_post_init(self, context: object) -> None:
        del context
        if len(self.expected_tools) != len(self.expected_statuses):
            raise ValueError("expected_tools and expected_statuses must have equal lengths")


@dataclass(frozen=True, slots=True)
class LiveAgentCaseResult:
    case_id: str
    passed: bool
    actual_tools: tuple[str, ...]
    actual_statuses: tuple[str, ...]
    actual_knowledge_sections: tuple[str, ...]
    approval_required: bool
    input_tokens: int
    output_tokens: int
    latency_ms: float
    estimated_cost_usd: Decimal | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class LiveAgentEvaluationResult:
    dataset_version: str
    model: str
    total_cases: int
    passed_cases: int
    tool_sequence_accuracy: float
    status_sequence_accuracy: float
    approval_accuracy: float
    knowledge_section_accuracy: float
    input_tokens: int
    output_tokens: int
    total_estimated_cost_usd: Decimal | None
    cases: tuple[LiveAgentCaseResult, ...]

    @property
    def pass_rate(self) -> float:
        return self.passed_cases / self.total_cases if self.total_cases else 0.0


def load_live_agent_cases(path: Path) -> list[LiveAgentCase]:
    adapter = TypeAdapter(LiveAgentCase)
    cases: list[LiveAgentCase] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        case = adapter.validate_json(line)
        if case.case_id in seen:
            raise ValueError(f"duplicate case_id at line {line_number}: {case.case_id}")
        seen.add(case.case_id)
        cases.append(case)
    if not cases:
        raise ValueError("live Agent evaluation dataset must not be empty")
    return cases


def evaluate_live_agent(
    cases: Sequence[LiveAgentCase],
    knowledge_manifest: Path,
    model: AgentModel,
    *,
    dataset_version: str,
    cost_rates: ModelCostRates | None = None,
) -> LiveAgentEvaluationResult:
    repository = _configured_repository()
    embedder = HashingEmbeddingProvider()
    ingest_knowledge_manifest(repository, embedder, knowledge_manifest)

    results: list[LiveAgentCaseResult] = []
    tool_matches: list[bool] = []
    status_matches: list[bool] = []
    approval_matches: list[bool] = []
    section_matches: list[bool] = []
    for case in cases:
        try:
            run = AgentRunner(
                repository,
                embedder,
                model,
                cost_rates=cost_rates,
            ).run(case.question, requester="live-evaluation")
            actual_tools = tuple(result.name for result in run.tool_results)
            actual_statuses = tuple(result.status.value for result in run.tool_results)
            actual_sections = tuple(
                citation.section
                for citation in run.answer.citations
                if citation.kind == "knowledge"
            )
            approval_required = any(
                result.status is ToolStatus.APPROVAL_REQUIRED
                for result in run.tool_results
            )
            tool_match = actual_tools == tuple(case.expected_tools)
            status_match = actual_statuses == tuple(
                status.value for status in case.expected_statuses
            )
            approval_match = approval_required is case.expected_approval_required
            section_match = set(case.required_knowledge_sections).issubset(actual_sections)
            passed = tool_match and status_match and approval_match and section_match
            tool_matches.append(tool_match)
            status_matches.append(status_match)
            approval_matches.append(approval_match)
            section_matches.append(section_match)
            results.append(
                LiveAgentCaseResult(
                    case_id=case.case_id,
                    passed=passed,
                    actual_tools=actual_tools,
                    actual_statuses=actual_statuses,
                    actual_knowledge_sections=actual_sections,
                    approval_required=approval_required,
                    input_tokens=run.telemetry.input_tokens,
                    output_tokens=run.telemetry.output_tokens,
                    latency_ms=run.telemetry.latency_ms,
                    estimated_cost_usd=run.telemetry.estimated_cost_usd,
                )
            )
        except Exception as error:
            tool_matches.append(False)
            status_matches.append(False)
            approval_matches.append(False)
            section_matches.append(False)
            results.append(
                LiveAgentCaseResult(
                    case_id=case.case_id,
                    passed=False,
                    actual_tools=(),
                    actual_statuses=(),
                    actual_knowledge_sections=(),
                    approval_required=False,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=0,
                    estimated_cost_usd=None,
                    error=f"{type(error).__name__}: {error}",
                )
            )

    estimated_costs = [
        result.estimated_cost_usd
        for result in results
        if result.estimated_cost_usd is not None
    ]
    total_cost = sum(estimated_costs, start=Decimal(0)) if estimated_costs else None
    return LiveAgentEvaluationResult(
        dataset_version=dataset_version,
        model=model.name,
        total_cases=len(results),
        passed_cases=sum(result.passed for result in results),
        tool_sequence_accuracy=_mean(tool_matches),
        status_sequence_accuracy=_mean(status_matches),
        approval_accuracy=_mean(approval_matches),
        knowledge_section_accuracy=_mean(section_matches),
        input_tokens=sum(result.input_tokens for result in results),
        output_tokens=sum(result.output_tokens for result in results),
        total_estimated_cost_usd=total_cost,
        cases=tuple(results),
    )


def _configured_repository() -> InMemoryRetailRepository:
    repository = InMemoryRetailRepository()
    repository.create_store(Store("store-1", "Chicago Loop"))
    repository.create_sku(Sku("sku-1", "Milk"))
    repository.adjust_inventory(
        InventoryAdjustment("live-eval-seed", "store-1", "sku-1", 12, "seed")
    )
    repository.create_device(
        Device(
            device_id="sensor-1",
            store_id="store-1",
            device_type=DeviceType.TEMPERATURE_SENSOR,
            display_name="Dairy sensor",
        )
    )
    repository.set_price(
        PriceChange(
            request_id="live-eval-price-seed",
            store_id="store-1",
            sku="sku-1",
            new_price=Decimal("3.99"),
            reason="seed",
        )
    )
    return repository


def _mean(values: Sequence[bool]) -> float:
    return sum(values) / len(values) if values else 0.0


def _cost_rates_from_environment() -> ModelCostRates | None:
    input_rate = os.getenv("OPENAI_INPUT_COST_PER_MILLION_USD")
    output_rate = os.getenv("OPENAI_OUTPUT_COST_PER_MILLION_USD")
    if input_rate is None and output_rate is None:
        return None
    if input_rate is None or output_rate is None:
        raise ValueError("both OpenAI cost-rate environment variables must be configured")
    try:
        return ModelCostRates(Decimal(input_rate), Decimal(output_rate))
    except InvalidOperation as error:
        raise ValueError("OpenAI cost-rate environment variables must be decimals") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run live end-to-end Copilot Agent evaluation")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("knowledge_manifest", type=Path)
    parser.add_argument("--dataset-version", default="copilot_live_agent_v1")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5.6-luna"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required for live Agent evaluation")
    cases = load_live_agent_cases(cast(Path, args.dataset))
    model_name = cast(str, args.model)
    result = evaluate_live_agent(
        cases,
        cast(Path, args.knowledge_manifest),
        OpenAIAgentModel(model_name),
        dataset_version=cast(str, args.dataset_version),
        cost_rates=_cost_rates_from_environment(),
    )
    output = asdict(result)
    output["pass_rate"] = result.pass_rate
    print(json.dumps(output, indent=2, sort_keys=True, default=str))
    return 0 if result.passed_cases == result.total_cases else 1


if __name__ == "__main__":
    raise SystemExit(main())
