"""Bounded multi-step agent loop with structured tool and citation contracts."""

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Protocol, cast

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from openai.types.responses import (
    FunctionToolParam,
    ResponseInputItemParam,
    ResponseInputParam,
)
from pydantic_core import to_jsonable_python

from smart_retail.copilot.models import CopilotAnswer, CopilotCitation, GeneratedCopilotAnswer
from smart_retail.copilot.service import GroundingError
from smart_retail.copilot.tools import (
    ToolDefinition,
    ToolExecutionResult,
    ToolGateway,
    ToolInvocation,
)
from smart_retail.knowledge.embedding import EmbeddingProvider
from smart_retail.knowledge.models import KnowledgeSearchResult
from smart_retail.observability import current_request_id
from smart_retail.repositories.base import RetailRepository

logger = logging.getLogger("smart_retail.copilot.agent")


@dataclass(frozen=True, slots=True)
class AgentTurn:
    tool_calls: tuple[ToolInvocation, ...] = ()
    answer: GeneratedCopilotAnswer | None = None
    usage: "ModelUsage" = field(default_factory=lambda: ModelUsage())

    def __post_init__(self) -> None:
        if bool(self.tool_calls) == (self.answer is not None):
            raise ValueError("an agent turn must contain either tool calls or a final answer")


class AgentSession(Protocol):
    def next_turn(self, tool_results: Sequence[ToolExecutionResult]) -> AgentTurn: ...


class AgentModel(Protocol):
    name: str

    def start(
        self,
        question: str,
        context: Sequence[KnowledgeSearchResult],
        tools: Sequence[ToolDefinition],
        *,
        requester: str,
    ) -> AgentSession: ...


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("token counts cannot be negative")


@dataclass(frozen=True, slots=True)
class ModelCostRates:
    input_per_million_usd: Decimal
    output_per_million_usd: Decimal

    def __post_init__(self) -> None:
        if self.input_per_million_usd < 0 or self.output_per_million_usd < 0:
            raise ValueError("model cost rates cannot be negative")

    def estimate(self, usage: ModelUsage) -> Decimal:
        cost = (
            Decimal(usage.input_tokens) * self.input_per_million_usd
            + Decimal(usage.output_tokens) * self.output_per_million_usd
        ) / Decimal(1_000_000)
        return cost.quantize(Decimal("0.000001"))


@dataclass(frozen=True, slots=True)
class AgentTelemetry:
    provider_attempts: int
    input_tokens: int
    output_tokens: int
    tool_calls: int
    latency_ms: float
    estimated_cost_usd: Decimal | None


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    answer: CopilotAnswer
    tool_results: tuple[ToolExecutionResult, ...]
    steps: int
    telemetry: AgentTelemetry


class AgentStepLimitError(RuntimeError):
    """Raised when a model does not reach a final answer within the configured bound."""


class AgentProtocolError(RuntimeError):
    """Raised when a provider returns neither tool calls nor a structured answer."""


class TransientAgentError(RuntimeError):
    """Raised when a model call may safely be retried."""


class AgentModelUnavailableError(RuntimeError):
    """Raised when bounded retries cannot recover a transient model failure."""


class AgentRunner:
    def __init__(
        self,
        repository: RetailRepository,
        embedder: EmbeddingProvider,
        model: AgentModel,
        *,
        maximum_steps: int = 6,
        minimum_score: float = 0.05,
        model_retry_delays: Sequence[float] = (0.25, 1.0),
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        cost_rates: ModelCostRates | None = None,
    ) -> None:
        if maximum_steps < 1:
            raise ValueError("maximum_steps must be positive")
        self._repository = repository
        self._embedder = embedder
        self._model = model
        self._maximum_steps = maximum_steps
        self._minimum_score = minimum_score
        if any(delay < 0 for delay in model_retry_delays):
            raise ValueError("model retry delays cannot be negative")
        self._model_retry_delays = tuple(model_retry_delays)
        self._sleep = sleep
        self._monotonic = monotonic
        self._cost_rates = cost_rates

    def run(
        self,
        question: str,
        *,
        requester: str,
        source_ids: Sequence[str] | None = None,
        top_k: int = 5,
    ) -> AgentRunResult:
        started_at = self._monotonic()
        query_embedding = self._embedder.embed_texts([question])[0]
        retrieved = self._repository.search_knowledge(
            query_embedding,
            source_ids=source_ids,
            limit=top_k,
        )
        context = [item for item in retrieved if item.score >= self._minimum_score]
        gateway = ToolGateway(self._repository)
        session = self._model.start(
            question,
            context,
            gateway.definitions,
            requester=requester,
        )
        all_results: list[ToolExecutionResult] = []
        latest_results: list[ToolExecutionResult] = []
        provider_attempts = 0
        usage = ModelUsage()
        for step in range(1, self._maximum_steps + 1):
            turn, attempts = self._next_turn(session, latest_results)
            provider_attempts += attempts
            usage = ModelUsage(
                input_tokens=usage.input_tokens + turn.usage.input_tokens,
                output_tokens=usage.output_tokens + turn.usage.output_tokens,
            )
            if turn.answer is not None:
                answer = _build_agent_answer(
                    turn.answer,
                    context,
                    all_results,
                    provider=self._model.name,
                )
                telemetry = AgentTelemetry(
                    provider_attempts=provider_attempts,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    tool_calls=len(all_results),
                    latency_ms=round((self._monotonic() - started_at) * 1000, 3),
                    estimated_cost_usd=(
                        self._cost_rates.estimate(usage) if self._cost_rates else None
                    ),
                )
                logger.info(
                    json.dumps(
                        {
                            "event": "copilot_agent_completed",
                            "request_id": current_request_id(),
                            "provider": self._model.name,
                            **cast(dict[str, object], to_jsonable_python(asdict(telemetry))),
                        },
                        sort_keys=True,
                    )
                )
                return AgentRunResult(answer, tuple(all_results), step, telemetry)

            latest_results = []
            for call in turn.tool_calls:
                result = gateway.execute(
                    ToolInvocation(
                        call_id=call.call_id,
                        name=call.name,
                        arguments=call.arguments,
                        requester=requester,
                    )
                )
                latest_results.append(result)
                logger.info(
                    json.dumps(
                        {
                            "event": "copilot_tool_completed",
                            "request_id": current_request_id(),
                            "step": step,
                            "call_id": result.call_id,
                            "tool_name": result.name,
                            "status": result.status.value,
                            "approval_id": result.approval_id,
                        },
                        sort_keys=True,
                    )
                )
            all_results.extend(latest_results)
        logger.warning(
            json.dumps(
                {
                    "event": "copilot_agent_step_limit",
                    "request_id": current_request_id(),
                    "maximum_steps": self._maximum_steps,
                    "provider": self._model.name,
                },
                sort_keys=True,
            )
        )
        raise AgentStepLimitError(
            f"agent exceeded maximum_steps={self._maximum_steps} without a final answer"
        )

    def _next_turn(
        self,
        session: AgentSession,
        tool_results: Sequence[ToolExecutionResult],
    ) -> tuple[AgentTurn, int]:
        for attempt in range(len(self._model_retry_delays) + 1):
            try:
                return session.next_turn(tool_results), attempt + 1
            except TransientAgentError as exc:
                if attempt == len(self._model_retry_delays):
                    attempts = attempt + 1
                    logger.error(
                        json.dumps(
                            {
                                "event": "copilot_model_unavailable",
                                "request_id": current_request_id(),
                                "attempts": attempts,
                                "provider": self._model.name,
                                "error_type": type(exc).__name__,
                            },
                            sort_keys=True,
                        )
                    )
                    raise AgentModelUnavailableError(
                        f"model unavailable after {attempts} attempts"
                    ) from exc
                delay = self._model_retry_delays[attempt]
                logger.warning(
                    json.dumps(
                        {
                            "event": "copilot_model_retry",
                            "request_id": current_request_id(),
                            "attempt": attempt + 1,
                            "next_delay_seconds": delay,
                            "provider": self._model.name,
                            "error_type": type(exc).__name__,
                        },
                        sort_keys=True,
                    )
                )
                self._sleep(delay)
        raise AssertionError("unreachable retry state")


class OpenAIAgentModel:
    def __init__(
        self,
        model: str,
        client: OpenAI | None = None,
        *,
        request_timeout_seconds: float = 20.0,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        self._model = model
        self._client = (client or OpenAI()).with_options(
            max_retries=0,
            timeout=request_timeout_seconds,
        )
        self.name = f"openai_responses_agent:{model}"

    def start(
        self,
        question: str,
        context: Sequence[KnowledgeSearchResult],
        tools: Sequence[ToolDefinition],
        *,
        requester: str,
    ) -> AgentSession:
        return _OpenAIAgentSession(
            client=self._client,
            model=self._model,
            question=question,
            context=context,
            tools=tools,
            requester=requester,
        )


class _OpenAIAgentSession:
    def __init__(
        self,
        *,
        client: OpenAI,
        model: str,
        question: str,
        context: Sequence[KnowledgeSearchResult],
        tools: Sequence[ToolDefinition],
        requester: str,
    ) -> None:
        rendered_context = "\n\n".join(
            f"SOURCE {item.citation}\n{item.title} / {item.section}\n{item.content}"
            for item in context
        )
        initial_message = {
            "role": "user",
            "content": (
                f"REQUESTER {requester}\nQUESTION\n{question}\n\n"
                f"RETRIEVED SOURCES\n{rendered_context}"
            ),
        }
        self._input = [cast(ResponseInputItemParam, initial_message)]
        self._tools = [
            cast(FunctionToolParam, definition.as_openai_tool()) for definition in tools
        ]
        self._client = client
        self._model = model
        self._submitted_tool_results: set[str] = set()

    def next_turn(self, tool_results: Sequence[ToolExecutionResult]) -> AgentTurn:
        for result in tool_results:
            if result.call_id in self._submitted_tool_results:
                continue
            payload = cast(dict[str, object], to_jsonable_python(asdict(result)))
            payload["evidence_id"] = result.citation
            self._input.append(
                cast(
                    ResponseInputItemParam,
                    {
                        "type": "function_call_output",
                        "call_id": result.call_id,
                        "output": json.dumps(payload, sort_keys=True),
                    },
                )
            )
            self._submitted_tool_results.add(result.call_id)

        try:
            response = self._client.responses.parse(
                model=self._model,
                store=False,
                input=cast(ResponseInputParam, self._input),
                instructions=(
                    "Use tools when operational data is required. Treat tool errors and "
                    "approval_required as results, not successes. Cite exact SOURCE IDs or "
                    "tool evidence_id values. Never claim a high-risk write executed while "
                    "it is awaiting approval."
                ),
                tools=self._tools,
                text_format=GeneratedCopilotAnswer,
                parallel_tool_calls=True,
                max_tool_calls=8,
            )
        except (
            APIConnectionError,
            APITimeoutError,
            InternalServerError,
            RateLimitError,
        ) as exc:
            raise TransientAgentError(f"transient OpenAI error: {type(exc).__name__}") from exc
        output_items = [
            cast(ResponseInputItemParam, item.model_dump(mode="json", exclude_none=True))
            for item in response.output
        ]
        self._input.extend(output_items)

        tool_calls: list[ToolInvocation] = []
        for item in response.output:
            if item.type != "function_call":
                continue
            raw_arguments = json.loads(item.arguments)
            if not isinstance(raw_arguments, dict):
                raise AgentProtocolError("function-call arguments must be a JSON object")
            tool_calls.append(
                ToolInvocation(
                    call_id=item.call_id,
                    name=item.name,
                    arguments=cast(dict[str, object], raw_arguments),
                )
            )
        response_usage = response.usage
        usage = ModelUsage(
            input_tokens=response_usage.input_tokens if response_usage else 0,
            output_tokens=response_usage.output_tokens if response_usage else 0,
        )
        if tool_calls:
            return AgentTurn(tool_calls=tuple(tool_calls), usage=usage)
        if response.output_parsed is None:
            raise AgentProtocolError("OpenAI response had no tool calls or parsed final answer")
        return AgentTurn(answer=response.output_parsed, usage=usage)


def _build_agent_answer(
    generated: GeneratedCopilotAnswer,
    context: Sequence[KnowledgeSearchResult],
    tool_results: Sequence[ToolExecutionResult],
    *,
    provider: str,
) -> CopilotAnswer:
    knowledge = {item.citation: item for item in context}
    tools = {item.citation: item for item in tool_results}
    allowed = set(knowledge) | set(tools)
    unknown = [citation for citation in generated.citations if citation not in allowed]
    if unknown:
        raise GroundingError(f"agent cited evidence that was not available: {unknown}")
    if generated.insufficient_evidence and generated.citations:
        raise GroundingError("an insufficient-evidence answer cannot include citations")
    if not generated.insufficient_evidence and not generated.citations:
        raise GroundingError("a supported agent answer must cite source or tool evidence")

    citations: list[CopilotCitation] = []
    for citation in dict.fromkeys(generated.citations):
        if source := knowledge.get(citation):
            citations.append(
                CopilotCitation(
                    kind="knowledge",
                    citation=source.citation,
                    source_id=source.source_id,
                    source_version=source.source_version,
                    title=source.title,
                    section=source.section,
                )
            )
        elif result := tools.get(citation):
            citations.append(
                CopilotCitation(
                    kind="tool",
                    citation=result.citation,
                    source_id=result.name,
                    source_version="runtime",
                    title=f"Tool result: {result.status.value}",
                    section=result.call_id,
                )
            )
    return CopilotAnswer(
        answer=generated.answer,
        citations=tuple(citations),
        insufficient_evidence=generated.insufficient_evidence,
        provider=provider,
        retrieved_chunks=len(context),
    )
