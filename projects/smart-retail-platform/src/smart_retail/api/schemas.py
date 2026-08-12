"""HTTP request and response contracts."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from smart_retail.copilot.tools import ToolStatus
from smart_retail.domain import ActorRole, ApprovalStatus, DeviceStatus, DeviceType


class StoreCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    store_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)


class StoreResponse(StoreCreate):
    pass


class SkuCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)


class SkuResponse(SkuCreate):
    pass


class InventoryAdjustmentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    request_id: str = Field(min_length=1, max_length=128)
    store_id: str = Field(min_length=1, max_length=64)
    sku: str = Field(min_length=1, max_length=64)
    quantity_delta: int
    reason: str = Field(min_length=1, max_length=500)


class InventoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    store_id: str
    sku: str
    quantity: int = Field(ge=0)
    updated_at: datetime


class DeviceCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    device_id: str = Field(min_length=1, max_length=128)
    store_id: str = Field(min_length=1, max_length=64)
    device_type: DeviceType
    display_name: str = Field(min_length=1, max_length=200)
    status: DeviceStatus = DeviceStatus.ACTIVE


class DeviceResponse(DeviceCreate):
    model_config = ConfigDict(from_attributes=True)

    registered_at: datetime


class DeviceEventCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event_id: str = Field(min_length=1, max_length=128)
    device_id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=100)
    observed_at: datetime
    payload: dict[str, object] = Field(default_factory=dict)


class DeviceEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    device_id: str
    event_type: str
    observed_at: datetime
    received_at: datetime
    payload: dict[str, object]


class HealthResponse(BaseModel):
    status: str
    storage: str


class OperationAuditEventResponse(BaseModel):
    event_id: str
    actor_id: str
    actor_role: ActorRole
    action: str
    resource_type: str
    resource_id: str
    request_id: str | None
    occurred_at: datetime


class AnalyticsRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    dataset_version: str
    input_rows: int = Field(ge=0)
    anomaly_detector: str
    forecaster: str
    created_at: datetime


class InventoryAnomalyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    store_id: str
    sku: str
    business_date: date
    is_anomaly: bool
    reasons: tuple[str, ...]
    trailing_demand: float | None


class DemandForecastResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    store_id: str
    sku: str
    target_date: date
    predicted_units: float = Field(ge=0)
    observed_units: int = Field(ge=0)
    history_size: int = Field(gt=0)


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=1000)
    source_ids: list[str] | None = None
    limit: int = Field(default=5, ge=1, le=20)


class KnowledgeSearchResponse(BaseModel):
    citation: str
    source_id: str
    source_version: str
    title: str
    section: str
    content: str
    score: float = Field(ge=-1, le=1)


class CopilotAskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=2000)
    source_ids: list[str] | None = None
    top_k: int = Field(default=5, ge=1, le=10)


class CopilotCitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: Literal["knowledge", "tool"]
    citation: str
    source_id: str
    source_version: str
    title: str
    section: str


class CopilotAnswerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    answer: str
    citations: tuple[CopilotCitationResponse, ...]
    insufficient_evidence: bool
    provider: str
    retrieved_chunks: int = Field(ge=0)


class ApprovalDecisionRequest(BaseModel):
    approved: bool


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    approval_id: str
    tool_name: str
    call_id: str
    arguments: dict[str, object]
    requester: str
    reason: str
    status: ApprovalStatus
    created_at: datetime
    decided_by: str | None
    decided_role: ActorRole | None
    decided_at: datetime | None
    result: dict[str, object] | None
    error: str | None


class AgentAskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=2000)
    source_ids: list[str] | None = None
    top_k: int = Field(default=5, ge=1, le=10)


class ToolExecutionResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    call_id: str
    name: str
    status: ToolStatus
    output: dict[str, object] | None
    error: str | None
    approval_id: str | None


class AgentTelemetryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider_attempts: int = Field(ge=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    estimated_cost_usd: Decimal | None


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    answer: CopilotAnswerResponse
    tool_results: tuple[ToolExecutionResultResponse, ...]
    steps: int = Field(ge=1)
    telemetry: AgentTelemetryResponse
