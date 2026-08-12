"""Typed business tools and a policy-aware execution gateway."""

from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_core import to_jsonable_python

from smart_retail.domain import (
    ActorRole,
    ApprovalRequest,
    ApprovalStatus,
    Device,
    DomainValidationError,
    InventoryAdjustment,
    PriceChange,
    WorkOrderPriority,
    WorkOrderRequest,
)
from smart_retail.repositories.base import (
    IdempotencyConflictError,
    ResourceNotFoundError,
    RetailRepository,
)


class ToolRisk(StrEnum):
    READ = "read"
    LOW_WRITE = "low_write"
    HIGH_WRITE = "high_write"


class ToolStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, object]
    risk: ToolRisk

    def as_openai_tool(self) -> dict[str, object]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "strict": True,
        }


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    call_id: str
    name: str
    arguments: dict[str, object]
    requester: str = "copilot-user"


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    call_id: str
    name: str
    status: ToolStatus
    output: dict[str, object] | None = None
    error: str | None = None
    approval_id: str | None = None

    @property
    def citation(self) -> str:
        return f"tool:{self.name}#{self.call_id}"


class _ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GetInventoryArguments(_ToolArguments):
    store_id: str = Field(min_length=1, max_length=64)
    sku: str = Field(min_length=1, max_length=64)


class GetDeviceArguments(_ToolArguments):
    device_id: str = Field(min_length=1, max_length=128)


class GetPriceArguments(GetInventoryArguments):
    pass


class GetWorkOrderArguments(_ToolArguments):
    ticket_id: str = Field(min_length=1, max_length=128)


class CreateWorkOrderArguments(_ToolArguments):
    request_id: str = Field(min_length=1, max_length=128)
    store_id: str = Field(min_length=1, max_length=64)
    category: str = Field(min_length=1, max_length=100)
    priority: WorkOrderPriority
    summary: str = Field(min_length=1, max_length=500)


class AdjustInventoryArguments(_ToolArguments):
    request_id: str = Field(min_length=1, max_length=128)
    store_id: str = Field(min_length=1, max_length=64)
    sku: str = Field(min_length=1, max_length=64)
    quantity_delta: int
    reason: str = Field(min_length=1, max_length=500)


class SetPriceArguments(_ToolArguments):
    request_id: str = Field(min_length=1, max_length=128)
    store_id: str = Field(min_length=1, max_length=64)
    sku: str = Field(min_length=1, max_length=64)
    new_price: Decimal = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)
    currency: str = Field(default="USD", min_length=3, max_length=3)


_TOOL_MODELS: dict[str, type[_ToolArguments]] = {
    "get_inventory": GetInventoryArguments,
    "get_device": GetDeviceArguments,
    "get_price": GetPriceArguments,
    "get_work_order": GetWorkOrderArguments,
    "create_work_order": CreateWorkOrderArguments,
    "adjust_inventory": AdjustInventoryArguments,
    "set_price": SetPriceArguments,
}

_TOOL_METADATA = {
    "get_inventory": (
        "Read current inventory for one store and SKU.",
        ToolRisk.READ,
    ),
    "get_device": ("Read a registered device and its current status.", ToolRisk.READ),
    "get_price": ("Read the current price for one store and SKU.", ToolRisk.READ),
    "get_work_order": ("Read a work order by ticket ID.", ToolRisk.READ),
    "create_work_order": (
        "Create an idempotent operational work order.",
        ToolRisk.LOW_WRITE,
    ),
    "adjust_inventory": (
        "Adjust inventory. This high-risk write requires human approval.",
        ToolRisk.HIGH_WRITE,
    ),
    "set_price": (
        "Set a store/SKU price. This high-risk write requires human approval.",
        ToolRisk.HIGH_WRITE,
    ),
}

_APPROVER_ROLES: dict[str, frozenset[ActorRole]] = {
    "adjust_inventory": frozenset({ActorRole.MANAGER, ActorRole.ADMIN}),
    "set_price": frozenset({ActorRole.PRICING_LEAD, ActorRole.ADMIN}),
}


class ToolPermissionError(PermissionError):
    """Raised when an actor cannot approve a high-risk tool."""


def role_can_approve(tool_name: str, role: ActorRole) -> bool:
    """Return the server-side approval policy decision for a tool and role."""

    return role in _APPROVER_ROLES.get(tool_name, frozenset())


class ToolGateway:
    def __init__(self, repository: RetailRepository) -> None:
        self._repository = repository

    @property
    def definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name=name,
                description=_TOOL_METADATA[name][0],
                parameters=cast(dict[str, object], model.model_json_schema()),
                risk=_TOOL_METADATA[name][1],
            )
            for name, model in _TOOL_MODELS.items()
        ]

    def execute(
        self,
        invocation: ToolInvocation,
    ) -> ToolExecutionResult:
        arguments_model = _TOOL_MODELS.get(invocation.name)
        if arguments_model is None:
            return self._error(invocation, f"unknown tool: {invocation.name}")
        try:
            arguments = arguments_model.model_validate(invocation.arguments)
        except ValidationError as error:
            return self._error(invocation, f"invalid tool arguments: {error}")

        risk = _TOOL_METADATA[invocation.name][1]
        if risk is ToolRisk.HIGH_WRITE:
            approval_id = _approval_id(invocation)
            reason_value = arguments.model_dump(mode="json").get("reason")
            approval = self._repository.create_approval(
                ApprovalRequest(
                    approval_id=approval_id,
                    tool_name=invocation.name,
                    call_id=invocation.call_id,
                    arguments=arguments.model_dump(mode="json"),
                    requester=invocation.requester,
                    reason=str(reason_value or f"Copilot requested {invocation.name}"),
                )
            )
            return ToolExecutionResult(
                call_id=invocation.call_id,
                name=invocation.name,
                status=ToolStatus.APPROVAL_REQUIRED,
                output={"arguments": arguments.model_dump(mode="json")},
                approval_id=approval.approval_id,
            )
        try:
            output = self._dispatch(invocation.name, arguments)
        except (ResourceNotFoundError, IdempotencyConflictError, DomainValidationError) as error:
            return self._error(invocation, str(error))
        return ToolExecutionResult(
            call_id=invocation.call_id,
            name=invocation.name,
            status=ToolStatus.SUCCESS,
            output=output,
        )

    def decide_and_execute(
        self,
        approval_id: str,
        *,
        approved: bool,
        actor_id: str,
        actor_role: ActorRole,
    ) -> ApprovalRequest:
        approval = self._repository.get_approval(approval_id)
        if approval is None:
            raise ResourceNotFoundError(f"approval not found: {approval_id}")
        if not role_can_approve(approval.tool_name, actor_role):
            raise ToolPermissionError(
                f"role {actor_role.value} cannot approve tool {approval.tool_name}"
            )
        decided = self._repository.decide_approval(
            approval_id,
            approved=approved,
            actor_id=actor_id,
            actor_role=actor_role,
        )
        if decided.status is ApprovalStatus.REJECTED:
            return decided

        claimed = self._repository.claim_approval_execution(approval_id)
        invocation = ToolInvocation(
            call_id=claimed.call_id,
            name=claimed.tool_name,
            arguments=dict(claimed.arguments),
            requester=claimed.requester,
        )
        arguments_model = _TOOL_MODELS[invocation.name]
        arguments = arguments_model.model_validate(invocation.arguments)
        try:
            output = self._dispatch(invocation.name, arguments)
        except (ResourceNotFoundError, IdempotencyConflictError, DomainValidationError) as error:
            return self._repository.complete_approval_execution(
                approval_id,
                result=None,
                error=str(error),
            )
        return self._repository.complete_approval_execution(
            approval_id,
            result=output,
            error=None,
        )

    def _dispatch(
        self,
        name: str,
        arguments: _ToolArguments,
    ) -> dict[str, object]:
        if name == "get_inventory":
            parsed = cast(GetInventoryArguments, arguments)
            snapshot = self._repository.get_inventory(parsed.store_id, parsed.sku)
            if snapshot is None:
                raise ResourceNotFoundError(
                    f"inventory not found for store={parsed.store_id}, sku={parsed.sku}"
                )
            return _json_output(asdict(snapshot))
        if name == "get_device":
            parsed = cast(GetDeviceArguments, arguments)
            device = self._repository.get_device(parsed.device_id)
            if device is None:
                raise ResourceNotFoundError(f"device not found: {parsed.device_id}")
            return _device_output(device)
        if name == "get_price":
            parsed = cast(GetPriceArguments, arguments)
            price = self._repository.get_price(parsed.store_id, parsed.sku)
            if price is None:
                raise ResourceNotFoundError(
                    f"price not found for store={parsed.store_id}, sku={parsed.sku}"
                )
            return _json_output(asdict(price))
        if name == "get_work_order":
            parsed = cast(GetWorkOrderArguments, arguments)
            work_order = self._repository.get_work_order(parsed.ticket_id)
            if work_order is None:
                raise ResourceNotFoundError(f"work order not found: {parsed.ticket_id}")
            return _json_output(asdict(work_order))
        if name == "create_work_order":
            parsed = cast(CreateWorkOrderArguments, arguments)
            work_order = self._repository.create_work_order(
                WorkOrderRequest(
                    request_id=parsed.request_id,
                    store_id=parsed.store_id,
                    category=parsed.category,
                    priority=parsed.priority,
                    summary=parsed.summary,
                )
            )
            return _json_output(asdict(work_order))
        if name == "adjust_inventory":
            parsed = cast(AdjustInventoryArguments, arguments)
            snapshot = self._repository.adjust_inventory(
                InventoryAdjustment(
                    request_id=parsed.request_id,
                    store_id=parsed.store_id,
                    sku=parsed.sku,
                    quantity_delta=parsed.quantity_delta,
                    reason=parsed.reason,
                )
            )
            return _json_output(asdict(snapshot))
        if name == "set_price":
            parsed = cast(SetPriceArguments, arguments)
            price = self._repository.set_price(
                PriceChange(
                    request_id=parsed.request_id,
                    store_id=parsed.store_id,
                    sku=parsed.sku,
                    new_price=parsed.new_price,
                    reason=parsed.reason,
                    currency=parsed.currency,
                )
            )
            return _json_output(asdict(price))
        raise RuntimeError(f"tool dispatcher is missing an implementation: {name}")

    @staticmethod
    def _error(invocation: ToolInvocation, message: str) -> ToolExecutionResult:
        return ToolExecutionResult(
            call_id=invocation.call_id,
            name=invocation.name,
            status=ToolStatus.ERROR,
            error=message,
        )


def _device_output(device: Device) -> dict[str, object]:
    return _json_output({
        "device_id": device.device_id,
        "store_id": device.store_id,
        "device_type": device.device_type.value,
        "display_name": device.display_name,
        "status": device.status.value,
        "registered_at": device.registered_at,
    })


def _approval_id(invocation: ToolInvocation) -> str:
    identity = f"{invocation.name}\n{invocation.arguments}"
    return f"approval-{sha256(identity.encode('utf-8')).hexdigest()[:20]}"


def _json_output(value: object) -> dict[str, object]:
    return cast(dict[str, object], to_jsonable_python(value))
