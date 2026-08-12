"""FastAPI application for the first retail operations vertical slice."""

import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal, InvalidOperation
from typing import Annotated, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from starlette.responses import Response

from smart_retail.api.schemas import (
    AgentAskRequest,
    AgentRunResponse,
    AnalyticsRunResponse,
    ApprovalDecisionRequest,
    ApprovalResponse,
    CopilotAnswerResponse,
    CopilotAskRequest,
    DemandForecastResponse,
    DeviceCreate,
    DeviceEventCreate,
    DeviceEventResponse,
    DeviceResponse,
    HealthResponse,
    InventoryAdjustmentCreate,
    InventoryAnomalyResponse,
    InventoryResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    OperationAuditEventResponse,
    SkuCreate,
    SkuResponse,
    StoreCreate,
    StoreResponse,
)
from smart_retail.copilot.agent import (
    AgentModel,
    AgentModelUnavailableError,
    AgentProtocolError,
    AgentRunner,
    AgentStepLimitError,
    ModelCostRates,
    OpenAIAgentModel,
)
from smart_retail.copilot.generators import (
    AnswerGenerator,
    ExtractiveAnswerGenerator,
    FallbackAnswerGenerator,
    OpenAIAnswerGenerator,
)
from smart_retail.copilot.service import CopilotService, GroundingError
from smart_retail.copilot.tools import ToolGateway, ToolPermissionError
from smart_retail.domain import (
    ActorRole,
    AuditActor,
    Device,
    DeviceEvent,
    DomainValidationError,
    InventoryAdjustment,
    InventoryWouldBecomeNegativeError,
    Sku,
    Store,
)
from smart_retail.knowledge.embedding import (
    CachingEmbeddingProvider,
    EmbeddingProvider,
    HashingEmbeddingProvider,
)
from smart_retail.observability import bind_request_id, reset_request_id
from smart_retail.repositories import InMemoryRetailRepository, RetailRepository
from smart_retail.repositories.base import (
    IdempotencyConflictError,
    ResourceAlreadyExistsError,
    ResourceNotFoundError,
)
from smart_retail.security import ApiKeyAuthenticator, Principal

request_logger = logging.getLogger("smart_retail.http")


def _configure_application_logger(logger: logging.Logger) -> None:
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)


def _default_repository() -> RetailRepository:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return InMemoryRetailRepository()

    from smart_retail.repositories.postgres import (
        PostgresRetailRepository,
        build_session_factory,
    )

    return PostgresRetailRepository(build_session_factory(database_url))


def _repository(request: Request) -> RetailRepository:
    return cast(RetailRepository, request.app.state.repository)


def _embedding_provider(request: Request) -> EmbeddingProvider:
    return cast(EmbeddingProvider, request.app.state.embedding_provider)


def _answer_generator(request: Request) -> AnswerGenerator:
    return cast(AnswerGenerator, request.app.state.answer_generator)


def _agent_model(request: Request) -> AgentModel | None:
    return cast(AgentModel | None, request.app.state.agent_model)


def _authenticated_principal(
    request: Request,
    api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Principal:
    authenticator = cast(ApiKeyAuthenticator, request.app.state.authenticator)
    principal = authenticator.authenticate(api_key)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="a valid X-API-Key is required",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return principal


def _default_answer_generator() -> AnswerGenerator:
    if os.getenv("OPENAI_API_KEY"):
        return FallbackAnswerGenerator(
            OpenAIAnswerGenerator(model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna")),
            ExtractiveAnswerGenerator(),
        )
    return ExtractiveAnswerGenerator()


def _default_agent_model() -> AgentModel | None:
    if not os.getenv("OPENAI_API_KEY"):
        return None
    return OpenAIAgentModel(model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna"))


def _default_cost_rates() -> ModelCostRates | None:
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


RepositoryDependency = Annotated[RetailRepository, Depends(_repository)]
EmbeddingDependency = Annotated[EmbeddingProvider, Depends(_embedding_provider)]
AnswerGeneratorDependency = Annotated[AnswerGenerator, Depends(_answer_generator)]
AgentModelDependency = Annotated[AgentModel | None, Depends(_agent_model)]
AuthenticatedPrincipalDependency = Annotated[Principal, Depends(_authenticated_principal)]
EventLimitQuery = Annotated[int, Query(ge=1, le=100)]
ResultLimitQuery = Annotated[int, Query(ge=1, le=500)]


def _require_roles(principal: Principal, allowed_roles: frozenset[ActorRole]) -> None:
    if principal.role not in allowed_roles:
        allowed = ", ".join(sorted(role.value for role in allowed_roles))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"role {principal.role.value} is not allowed; required one of: {allowed}",
        )


def _audit_actor(principal: Principal) -> AuditActor:
    return AuditActor(actor_id=principal.actor_id, role=principal.role)


def create_app(
    repository: RetailRepository | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    answer_generator: AnswerGenerator | None = None,
    agent_model: AgentModel | None = None,
    authenticator: ApiKeyAuthenticator | None = None,
    model_cost_rates: ModelCostRates | None = None,
) -> FastAPI:
    """Build an app; explicit repository injection keeps API tests fast and isolated."""

    _configure_application_logger(request_logger)
    _configure_application_logger(logging.getLogger("smart_retail.copilot.agent"))

    app = FastAPI(
        title="Smart Retail Operations API",
        version="0.2.0",
        description="Retail operations plus versioned inventory intelligence results.",
    )
    app.state.repository = repository or _default_repository()
    app.state.embedding_provider = embedding_provider or CachingEmbeddingProvider(
        HashingEmbeddingProvider()
    )
    app.state.answer_generator = answer_generator or _default_answer_generator()
    app.state.agent_model = agent_model or _default_agent_model()
    app.state.authenticator = authenticator or ApiKeyAuthenticator.from_environment()
    app.state.model_cost_rates = model_cost_rates or _default_cost_rates()

    @app.middleware("http")
    async def observe_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        started_at = time.monotonic()
        request_id_token = bind_request_id(request_id)
        try:
            try:
                response = await call_next(request)
            except Exception:
                request_logger.exception(
                    json.dumps(
                        {
                            "event": "http_request_failed",
                            "request_id": request_id,
                            "method": request.method,
                            "path": request.url.path,
                            "status_code": 500,
                            "latency_ms": round((time.monotonic() - started_at) * 1000, 3),
                        },
                        sort_keys=True,
                    )
                )
                raise
            response.headers["X-Request-ID"] = request_id
            request_logger.info(
                json.dumps(
                    {
                        "event": "http_request_completed",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "latency_ms": round((time.monotonic() - started_at) * 1000, 3),
                    },
                    sort_keys=True,
                )
            )
            return response
        finally:
            reset_request_id(request_id_token)

    @app.get("/health", response_model=HealthResponse, tags=["operations"])
    def health(repo: RepositoryDependency) -> HealthResponse:
        return HealthResponse(status="ok", storage=type(repo).__name__)

    @app.post(
        "/stores",
        response_model=StoreResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["catalog"],
    )
    def create_store(
        payload: StoreCreate,
        repo: RepositoryDependency,
        principal: AuthenticatedPrincipalDependency,
    ) -> StoreResponse:
        _require_roles(principal, frozenset({ActorRole.ADMIN}))
        try:
            created = repo.create_store(
                Store(payload.store_id, payload.name),
                actor=_audit_actor(principal),
            )
        except ResourceAlreadyExistsError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        return StoreResponse(store_id=created.store_id, name=created.name)

    @app.post(
        "/skus",
        response_model=SkuResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["catalog"],
    )
    def create_sku(
        payload: SkuCreate,
        repo: RepositoryDependency,
        principal: AuthenticatedPrincipalDependency,
    ) -> SkuResponse:
        _require_roles(principal, frozenset({ActorRole.ADMIN}))
        try:
            created = repo.create_sku(
                Sku(payload.sku, payload.name),
                actor=_audit_actor(principal),
            )
        except ResourceAlreadyExistsError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        return SkuResponse(sku=created.sku, name=created.name)

    @app.post(
        "/devices",
        response_model=DeviceResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["devices"],
    )
    def create_device(
        payload: DeviceCreate,
        repo: RepositoryDependency,
        principal: AuthenticatedPrincipalDependency,
    ) -> DeviceResponse:
        _require_roles(principal, frozenset({ActorRole.MANAGER, ActorRole.ADMIN}))
        try:
            created = repo.create_device(
                Device(
                    device_id=payload.device_id,
                    store_id=payload.store_id,
                    device_type=payload.device_type,
                    display_name=payload.display_name,
                    status=payload.status,
                ),
                actor=_audit_actor(principal),
            )
        except ResourceNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ResourceAlreadyExistsError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        return DeviceResponse.model_validate(created)

    @app.get(
        "/devices/{device_id}",
        response_model=DeviceResponse,
        tags=["devices"],
    )
    def get_device(device_id: str, repo: RepositoryDependency) -> DeviceResponse:
        device = repo.get_device(device_id)
        if device is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"device not found: {device_id}",
            )
        return DeviceResponse.model_validate(device)

    @app.post(
        "/device-events",
        response_model=DeviceEventResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["device-events"],
    )
    def record_device_event(
        payload: DeviceEventCreate,
        repo: RepositoryDependency,
        principal: AuthenticatedPrincipalDependency,
    ) -> DeviceEventResponse:
        _require_roles(
            principal,
            frozenset({ActorRole.OPERATOR, ActorRole.MANAGER, ActorRole.ADMIN}),
        )
        try:
            event = DeviceEvent(
                event_id=payload.event_id,
                device_id=payload.device_id,
                event_type=payload.event_type,
                observed_at=payload.observed_at,
                payload=payload.payload,
            )
            record = repo.record_device_event(event, actor=_audit_actor(principal))
        except ResourceNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except IdempotencyConflictError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except DomainValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error
        return DeviceEventResponse.model_validate(record)

    @app.get(
        "/devices/{device_id}/events",
        response_model=list[DeviceEventResponse],
        tags=["device-events"],
    )
    def list_device_events(
        device_id: str,
        repo: RepositoryDependency,
        limit: EventLimitQuery = 50,
    ) -> list[DeviceEventResponse]:
        try:
            records = repo.list_device_events(device_id, limit)
        except ResourceNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        return [DeviceEventResponse.model_validate(record) for record in records]

    @app.get(
        "/inventory/{store_id}/{sku}",
        response_model=InventoryResponse,
        tags=["inventory"],
    )
    def get_inventory(store_id: str, sku: str, repo: RepositoryDependency) -> InventoryResponse:
        snapshot = repo.get_inventory(store_id, sku)
        if snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"inventory not found for store={store_id}, sku={sku}",
            )
        return InventoryResponse.model_validate(snapshot)

    @app.post(
        "/inventory/adjustments",
        response_model=InventoryResponse,
        tags=["inventory"],
    )
    def adjust_inventory(
        payload: InventoryAdjustmentCreate,
        repo: RepositoryDependency,
        principal: AuthenticatedPrincipalDependency,
    ) -> InventoryResponse:
        _require_roles(
            principal,
            frozenset({ActorRole.OPERATOR, ActorRole.MANAGER, ActorRole.ADMIN}),
        )
        try:
            adjustment = InventoryAdjustment(
                request_id=payload.request_id,
                store_id=payload.store_id,
                sku=payload.sku,
                quantity_delta=payload.quantity_delta,
                reason=payload.reason,
            )
            snapshot = repo.adjust_inventory(adjustment, actor=_audit_actor(principal))
        except ResourceNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except (InventoryWouldBecomeNegativeError, IdempotencyConflictError) as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except DomainValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
            ) from error
        return InventoryResponse.model_validate(snapshot)

    @app.get(
        "/analytics/runs/{run_id}",
        response_model=AnalyticsRunResponse,
        tags=["analytics"],
    )
    def get_analytics_run(run_id: str, repo: RepositoryDependency) -> AnalyticsRunResponse:
        run = repo.get_analytics_run(run_id)
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"analytics run not found: {run_id}",
            )
        return AnalyticsRunResponse.model_validate(run)

    @app.get(
        "/analytics/runs/{run_id}/anomalies",
        response_model=list[InventoryAnomalyResponse],
        tags=["analytics"],
    )
    def list_inventory_anomalies(
        run_id: str,
        repo: RepositoryDependency,
        limit: ResultLimitQuery = 100,
        store_id: str | None = None,
        sku: str | None = None,
    ) -> list[InventoryAnomalyResponse]:
        try:
            results = repo.list_inventory_anomalies(
                run_id,
                store_id=store_id,
                sku=sku,
                limit=limit,
            )
        except ResourceNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        return [InventoryAnomalyResponse.model_validate(result) for result in results]

    @app.get(
        "/analytics/runs/{run_id}/forecasts",
        response_model=list[DemandForecastResponse],
        tags=["analytics"],
    )
    def list_demand_forecasts(
        run_id: str,
        repo: RepositoryDependency,
        limit: ResultLimitQuery = 100,
        store_id: str | None = None,
        sku: str | None = None,
    ) -> list[DemandForecastResponse]:
        try:
            results = repo.list_demand_forecasts(
                run_id,
                store_id=store_id,
                sku=sku,
                limit=limit,
            )
        except ResourceNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        return [DemandForecastResponse.model_validate(result) for result in results]

    @app.post(
        "/knowledge/search",
        response_model=list[KnowledgeSearchResponse],
        tags=["knowledge"],
    )
    def search_knowledge(
        payload: KnowledgeSearchRequest,
        repo: RepositoryDependency,
        embedder: EmbeddingDependency,
    ) -> list[KnowledgeSearchResponse]:
        query_embedding = embedder.embed_texts([payload.query])[0]
        results = repo.search_knowledge(
            query_embedding,
            source_ids=payload.source_ids,
            limit=payload.limit,
        )
        return [
            KnowledgeSearchResponse(
                citation=result.citation,
                source_id=result.source_id,
                source_version=result.source_version,
                title=result.title,
                section=result.section,
                content=result.content,
                score=result.score,
            )
            for result in results
        ]

    @app.post(
        "/copilot/ask",
        response_model=CopilotAnswerResponse,
        tags=["copilot"],
    )
    def ask_copilot(
        payload: CopilotAskRequest,
        repo: RepositoryDependency,
        embedder: EmbeddingDependency,
        generator: AnswerGeneratorDependency,
    ) -> CopilotAnswerResponse:
        service = CopilotService(repo, embedder, generator)
        try:
            answer = service.ask(
                payload.question,
                source_ids=payload.source_ids,
                top_k=payload.top_k,
            )
        except GroundingError as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(error),
            ) from error
        return CopilotAnswerResponse.model_validate(answer)

    @app.post(
        "/copilot/agent",
        response_model=AgentRunResponse,
        tags=["copilot"],
    )
    def run_copilot_agent(
        payload: AgentAskRequest,
        repo: RepositoryDependency,
        embedder: EmbeddingDependency,
        model: AgentModelDependency,
        principal: AuthenticatedPrincipalDependency,
    ) -> AgentRunResponse:
        if model is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OPENAI_API_KEY is required for the live tool-calling agent",
            )
        try:
            result = AgentRunner(
                repo,
                embedder,
                model,
                cost_rates=cast(ModelCostRates | None, app.state.model_cost_rates),
            ).run(
                payload.question,
                requester=principal.actor_id,
                source_ids=payload.source_ids,
                top_k=payload.top_k,
            )
        except (
            GroundingError,
            AgentModelUnavailableError,
            AgentProtocolError,
            AgentStepLimitError,
        ) as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(error),
            ) from error
        return AgentRunResponse.model_validate(result)

    @app.get(
        "/audit-events",
        response_model=list[OperationAuditEventResponse],
        tags=["audit"],
    )
    def list_operation_audit_events(
        repo: RepositoryDependency,
        principal: AuthenticatedPrincipalDependency,
        limit: ResultLimitQuery = 100,
        actor_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> list[OperationAuditEventResponse]:
        _require_roles(principal, frozenset({ActorRole.ADMIN}))
        events = repo.list_operation_audit_events(
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            limit=limit,
        )
        return [
            OperationAuditEventResponse(
                event_id=event.event_id,
                actor_id=event.actor.actor_id,
                actor_role=event.actor.role,
                action=event.action,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                request_id=event.request_id,
                occurred_at=event.occurred_at,
            )
            for event in events
        ]

    @app.get(
        "/approvals/{approval_id}",
        response_model=ApprovalResponse,
        tags=["approvals"],
    )
    def get_approval(
        approval_id: str,
        repo: RepositoryDependency,
        principal: AuthenticatedPrincipalDependency,
    ) -> ApprovalResponse:
        del principal
        approval = repo.get_approval(approval_id)
        if approval is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"approval not found: {approval_id}",
            )
        return ApprovalResponse.model_validate(approval)

    @app.post(
        "/approvals/{approval_id}/decision",
        response_model=ApprovalResponse,
        tags=["approvals"],
    )
    def decide_approval(
        approval_id: str,
        payload: ApprovalDecisionRequest,
        repo: RepositoryDependency,
        principal: AuthenticatedPrincipalDependency,
    ) -> ApprovalResponse:
        gateway = ToolGateway(repo)
        try:
            approval = gateway.decide_and_execute(
                approval_id,
                approved=payload.approved,
                actor_id=principal.actor_id,
                actor_role=principal.role,
            )
        except ResourceNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ToolPermissionError as error:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
        except DomainValidationError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        return ApprovalResponse.model_validate(approval)

    return app


app = create_app()
