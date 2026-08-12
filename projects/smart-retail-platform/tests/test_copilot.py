from collections.abc import Sequence
from pathlib import Path

import pytest

from smart_retail.copilot.generators import (
    AnswerGeneration,
    ExtractiveAnswerGenerator,
    FallbackAnswerGenerator,
    TransientGenerationError,
)
from smart_retail.copilot.models import GeneratedCopilotAnswer
from smart_retail.copilot.service import CopilotService, GroundingError
from smart_retail.knowledge.embedding import HashingEmbeddingProvider
from smart_retail.knowledge.ingestion import ingest_knowledge_manifest
from smart_retail.knowledge.models import KnowledgeSearchResult
from smart_retail.repositories.memory import InMemoryRetailRepository

KNOWLEDGE_MANIFEST = Path(__file__).parents[1] / "data" / "knowledge" / "manifest.json"


class _UnknownCitationGenerator:
    name = "invalid_test_generator"

    def generate(
        self,
        question: str,
        context: Sequence[KnowledgeSearchResult],
    ) -> AnswerGeneration:
        del question, context
        return AnswerGeneration(
            answer=GeneratedCopilotAnswer(
                answer="Unsupported answer",
                citations=["invented-source@v9#fake"],
                insufficient_evidence=False,
            ),
            provider=self.name,
        )


class _UnavailableGenerator:
    name = "unavailable_test_provider"

    def generate(
        self,
        question: str,
        context: Sequence[KnowledgeSearchResult],
    ) -> AnswerGeneration:
        del question, context
        raise TransientGenerationError("temporary outage")


def configured_service() -> CopilotService:
    repository = InMemoryRetailRepository()
    embedder = HashingEmbeddingProvider()
    ingest_knowledge_manifest(repository, embedder, KNOWLEDGE_MANIFEST)
    return CopilotService(repository, embedder, ExtractiveAnswerGenerator())


def test_copilot_returns_answer_with_retrieved_citation() -> None:
    answer = configured_service().ask(
        "verified product above 5 degrees for 15 minutes priority one work order",
        source_ids=["refrigeration-manual"],
    )

    assert not answer.insufficient_evidence
    assert answer.citations[0].source_id == "refrigeration-manual"
    assert answer.citations[0].section == "High-temperature alarm"
    assert answer.provider == "extractive_fallback_v1"


def test_copilot_reports_insufficient_evidence_without_sources() -> None:
    repository = InMemoryRetailRepository()
    service = CopilotService(
        repository,
        HashingEmbeddingProvider(),
        ExtractiveAnswerGenerator(),
    )

    answer = service.ask("How do I repair an escalator?")

    assert answer.insufficient_evidence
    assert not answer.citations


def test_copilot_rejects_citation_not_present_in_retrieved_context() -> None:
    repository = InMemoryRetailRepository()
    embedder = HashingEmbeddingProvider()
    ingest_knowledge_manifest(repository, embedder, KNOWLEDGE_MANIFEST)
    service = CopilotService(repository, embedder, _UnknownCitationGenerator())

    with pytest.raises(GroundingError, match="not retrieved"):
        service.ask("inventory discrepancy recount")


def test_copilot_uses_deterministic_fallback_on_transient_provider_failure() -> None:
    repository = InMemoryRetailRepository()
    embedder = HashingEmbeddingProvider()
    ingest_knowledge_manifest(repository, embedder, KNOWLEDGE_MANIFEST)
    service = CopilotService(
        repository,
        embedder,
        FallbackAnswerGenerator(_UnavailableGenerator(), ExtractiveAnswerGenerator()),
    )

    answer = service.ask("inventory discrepancy recount")

    assert answer.provider == "extractive_fallback_v1"
    assert answer.citations[0].section == "Inventory discrepancy"
