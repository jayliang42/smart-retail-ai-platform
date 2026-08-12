"""Answer generator boundary with offline and OpenAI Responses implementations."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from smart_retail.copilot.models import GeneratedCopilotAnswer
from smart_retail.knowledge.models import KnowledgeSearchResult


@dataclass(frozen=True, slots=True)
class AnswerGeneration:
    answer: GeneratedCopilotAnswer
    provider: str


class AnswerGenerator(Protocol):
    name: str

    def generate(
        self,
        question: str,
        context: Sequence[KnowledgeSearchResult],
    ) -> AnswerGeneration: ...


class TransientGenerationError(RuntimeError):
    """Raised when a provider error is eligible for deterministic fallback."""


class ExtractiveAnswerGenerator:
    """Deterministic local fallback that returns the strongest retrieved passage."""

    name = "extractive_fallback_v1"

    def generate(
        self,
        question: str,
        context: Sequence[KnowledgeSearchResult],
    ) -> AnswerGeneration:
        del question
        if not context:
            return AnswerGeneration(
                answer=GeneratedCopilotAnswer(
                    answer="The available operational sources do not contain enough evidence.",
                    citations=[],
                    insufficient_evidence=True,
                ),
                provider=self.name,
            )
        strongest = context[0]
        return AnswerGeneration(
            answer=GeneratedCopilotAnswer(
                answer=strongest.content,
                citations=[strongest.citation],
                insufficient_evidence=False,
            ),
            provider=self.name,
        )


class OpenAIAnswerGenerator:
    """Structured grounded answers through the OpenAI Responses API."""

    def __init__(
        self,
        model: str,
        client: OpenAI | None = None,
        *,
        request_timeout_seconds: float = 20.0,
    ) -> None:
        if not model.strip():
            raise ValueError("OpenAI model cannot be blank")
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        self._model = model
        self._client = (client or OpenAI()).with_options(
            max_retries=2,
            timeout=request_timeout_seconds,
        )
        self.name = f"openai_responses:{model}"

    def generate(
        self,
        question: str,
        context: Sequence[KnowledgeSearchResult],
    ) -> AnswerGeneration:
        rendered_context = "\n\n".join(
            (
                f"SOURCE {item.citation}\n"
                f"TITLE {item.title}\n"
                f"SECTION {item.section}\n"
                f"CONTENT\n{item.content}"
            )
            for item in context
        )
        try:
            response = self._client.responses.parse(
                model=self._model,
                store=False,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Answer store-operations questions only from the supplied sources. "
                            "Return exact SOURCE identifiers in citations. If the sources do not "
                            "support an answer, set insufficient_evidence true and cite nothing."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"QUESTION\n{question}\n\nSOURCES\n{rendered_context}",
                    },
                ],
                text_format=GeneratedCopilotAnswer,
            )
        except (
            APIConnectionError,
            APITimeoutError,
            InternalServerError,
            RateLimitError,
        ) as exc:
            raise TransientGenerationError(
                f"transient OpenAI error: {type(exc).__name__}"
            ) from exc
        parsed = response.output_parsed
        if parsed is None:
            raise RuntimeError("OpenAI response did not contain a parsed Copilot answer")
        return AnswerGeneration(answer=parsed, provider=self.name)


class FallbackAnswerGenerator:
    """Route to a deterministic generator only for transient provider failures."""

    name = "transient_fallback_router_v1"

    def __init__(self, primary: AnswerGenerator, fallback: AnswerGenerator) -> None:
        self._primary = primary
        self._fallback = fallback

    def generate(
        self,
        question: str,
        context: Sequence[KnowledgeSearchResult],
    ) -> AnswerGeneration:
        try:
            return self._primary.generate(question, context)
        except TransientGenerationError:
            return self._fallback.generate(question, context)
