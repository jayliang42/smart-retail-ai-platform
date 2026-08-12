"""Grounded retrieval and citation validation for Copilot answers."""

from collections.abc import Sequence

from smart_retail.copilot.generators import AnswerGenerator
from smart_retail.copilot.models import CopilotAnswer, CopilotCitation, GeneratedCopilotAnswer
from smart_retail.knowledge.embedding import EmbeddingProvider
from smart_retail.knowledge.models import KnowledgeSearchResult
from smart_retail.repositories.base import RetailRepository


class GroundingError(RuntimeError):
    """Raised when a generated answer violates the retrieved-evidence contract."""


class CopilotService:
    def __init__(
        self,
        repository: RetailRepository,
        embedder: EmbeddingProvider,
        generator: AnswerGenerator,
        *,
        minimum_score: float = 0.05,
    ) -> None:
        self._repository = repository
        self._embedder = embedder
        self._generator = generator
        self._minimum_score = minimum_score

    def ask(
        self,
        question: str,
        *,
        source_ids: Sequence[str] | None = None,
        top_k: int = 5,
    ) -> CopilotAnswer:
        query_embedding = self._embedder.embed_texts([question])[0]
        retrieved = self._repository.search_knowledge(
            query_embedding,
            source_ids=source_ids,
            limit=top_k,
        )
        context = [item for item in retrieved if item.score >= self._minimum_score]
        generation = self._generator.generate(question, context)
        return build_grounded_answer(
            generation.answer,
            context,
            provider=generation.provider,
        )


def build_grounded_answer(
    generated: GeneratedCopilotAnswer,
    context: Sequence[KnowledgeSearchResult],
    *,
    provider: str,
) -> CopilotAnswer:
    available = {item.citation: item for item in context}
    unknown = [citation for citation in generated.citations if citation not in available]
    if unknown:
        raise GroundingError(f"answer cited sources that were not retrieved: {unknown}")
    if generated.insufficient_evidence and generated.citations:
        raise GroundingError("an insufficient-evidence answer cannot include citations")
    if not generated.insufficient_evidence and not generated.citations:
        raise GroundingError("a supported answer must include at least one citation")

    citations = tuple(
        CopilotCitation(
            kind="knowledge",
            citation=item.citation,
            source_id=item.source_id,
            source_version=item.source_version,
            title=item.title,
            section=item.section,
        )
        for citation in dict.fromkeys(generated.citations)
        if (item := available.get(citation)) is not None
    )
    return CopilotAnswer(
        answer=generated.answer,
        citations=citations,
        insufficient_evidence=generated.insufficient_evidence,
        provider=provider,
        retrieved_chunks=len(context),
    )
