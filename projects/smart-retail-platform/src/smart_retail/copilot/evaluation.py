"""Deterministic Copilot component evaluation over a versioned JSONL suite."""

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from smart_retail.copilot.tools import (
    ToolGateway,
    ToolInvocation,
    ToolStatus,
    role_can_approve,
)
from smart_retail.domain import (
    ActorRole,
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


class _EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    case_id: str = Field(min_length=1)


class RetrievalCase(_EvaluationCase):
    category: Literal["retrieval"]
    question: str = Field(min_length=1)
    expected_source_id: str = Field(min_length=1)
    expected_section: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)


class GroundingCase(_EvaluationCase):
    category: Literal["grounding"]
    available_citations: list[str]
    claimed_citations: list[str]
    insufficient_evidence: bool
    expected_valid: bool


class ToolCase(_EvaluationCase):
    category: Literal["tool"]
    tool_name: str = Field(min_length=1)
    arguments: dict[str, object]
    expected_status: ToolStatus


class ApprovalPolicyCase(_EvaluationCase):
    category: Literal["approval_policy"]
    tool_name: str = Field(min_length=1)
    role: ActorRole
    expected_allowed: bool


CopilotEvaluationCase = Annotated[
    RetrievalCase | GroundingCase | ToolCase | ApprovalPolicyCase,
    Field(discriminator="category"),
]
_CASE_ADAPTER = TypeAdapter(CopilotEvaluationCase)


@dataclass(frozen=True, slots=True)
class CopilotEvaluationResult:
    dataset_version: str
    total_cases: int
    passed_cases: int
    retrieval_cases: int
    retrieval_recall_at_k: float
    retrieval_mrr: float
    grounding_accuracy: float
    tool_contract_accuracy: float
    approval_policy_accuracy: float
    failed_case_ids: tuple[str, ...]

    @property
    def pass_rate(self) -> float:
        return self.passed_cases / self.total_cases if self.total_cases else 0.0


def load_evaluation_cases(path: Path) -> list[CopilotEvaluationCase]:
    cases: list[CopilotEvaluationCase] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        case = _CASE_ADAPTER.validate_json(raw_line)
        if case.case_id in seen:
            raise ValueError(f"duplicate case_id at line {line_number}: {case.case_id}")
        seen.add(case.case_id)
        cases.append(case)
    if not cases:
        raise ValueError("evaluation dataset must contain at least one case")
    return cases


def evaluate_copilot_components(
    cases: Sequence[CopilotEvaluationCase],
    knowledge_manifest: Path,
    *,
    dataset_version: str,
) -> CopilotEvaluationResult:
    retrieval_repository = InMemoryRetailRepository()
    embedder = HashingEmbeddingProvider()
    ingest_knowledge_manifest(retrieval_repository, embedder, knowledge_manifest)

    passed = 0
    retrieval_ranks: list[int | None] = []
    grounding_results: list[bool] = []
    tool_results: list[bool] = []
    approval_results: list[bool] = []
    failed_case_ids: list[str] = []

    for case in cases:
        if isinstance(case, RetrievalCase):
            results = retrieval_repository.search_knowledge(
                embedder.embed_texts([case.question])[0],
                source_ids=None,
                limit=case.top_k,
            )
            rank = next(
                (
                    index
                    for index, result in enumerate(results, 1)
                    if result.source_id == case.expected_source_id
                    and result.section == case.expected_section
                ),
                None,
            )
            retrieval_ranks.append(rank)
            passed += rank is not None
            if rank is None:
                failed_case_ids.append(case.case_id)
        elif isinstance(case, GroundingCase):
            actual_valid = _citation_contract_is_valid(case)
            correct = actual_valid is case.expected_valid
            grounding_results.append(correct)
            passed += correct
            if not correct:
                failed_case_ids.append(case.case_id)
        elif isinstance(case, ToolCase):
            result = _evaluate_tool_case(case)
            tool_results.append(result)
            passed += result
            if not result:
                failed_case_ids.append(case.case_id)
        else:
            result = role_can_approve(case.tool_name, case.role) is case.expected_allowed
            approval_results.append(result)
            passed += result
            if not result:
                failed_case_ids.append(case.case_id)

    return CopilotEvaluationResult(
        dataset_version=dataset_version,
        total_cases=len(cases),
        passed_cases=passed,
        retrieval_cases=len(retrieval_ranks),
        retrieval_recall_at_k=_mean([rank is not None for rank in retrieval_ranks]),
        retrieval_mrr=_mean([0.0 if rank is None else 1 / rank for rank in retrieval_ranks]),
        grounding_accuracy=_mean(grounding_results),
        tool_contract_accuracy=_mean(tool_results),
        approval_policy_accuracy=_mean(approval_results),
        failed_case_ids=tuple(failed_case_ids),
    )


def _citation_contract_is_valid(case: GroundingCase) -> bool:
    available = set(case.available_citations)
    unknown = any(citation not in available for citation in case.claimed_citations)
    if unknown:
        return False
    if case.insufficient_evidence:
        return not case.claimed_citations
    return bool(case.claimed_citations)


def _evaluate_tool_case(case: ToolCase) -> bool:
    repository = _configured_repository()
    result = ToolGateway(repository).execute(
        ToolInvocation(
            call_id=f"eval-{case.case_id}",
            name=case.tool_name,
            arguments=case.arguments,
            requester="evaluation-runner",
        )
    )
    return result.status is case.expected_status


def _configured_repository() -> InMemoryRetailRepository:
    repository = InMemoryRetailRepository()
    repository.create_store(Store("store-1", "Chicago Loop"))
    repository.create_sku(Sku("sku-1", "Milk"))
    repository.adjust_inventory(
        InventoryAdjustment("eval-seed", "store-1", "sku-1", 12, "seed")
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
            request_id="eval-price-seed",
            store_id="store-1",
            sku="sku-1",
            new_price=Decimal("3.99"),
            reason="seed",
        )
    )
    return repository


def _mean(values: Sequence[float | bool]) -> float:
    return sum(float(value) for value in values) / len(values) if values else 0.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate deterministic Copilot contracts")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("knowledge_manifest", type=Path)
    parser.add_argument("--dataset-version", default="copilot_eval_v1")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cases = load_evaluation_cases(cast(Path, args.dataset))
    result = evaluate_copilot_components(
        cases,
        cast(Path, args.knowledge_manifest),
        dataset_version=cast(str, args.dataset_version),
    )
    output = asdict(result)
    output["pass_rate"] = result.pass_rate
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if result.passed_cases == result.total_cases else 1


if __name__ == "__main__":
    raise SystemExit(main())
