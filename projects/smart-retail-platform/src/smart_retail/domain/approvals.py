"""Human-approval state for high-risk Copilot tool calls."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from smart_retail.domain.inventory import DomainValidationError


class ActorRole(StrEnum):
    OPERATOR = "operator"
    MANAGER = "manager"
    PRICING_LEAD = "pricing_lead"
    ADMIN = "admin"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    approval_id: str
    tool_name: str
    call_id: str
    arguments: Mapping[str, object]
    requester: str
    reason: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    decided_by: str | None = None
    decided_role: ActorRole | None = None
    decided_at: datetime | None = None
    result: Mapping[str, object] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("approval_id", "tool_name", "call_id", "requester", "reason"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise DomainValidationError(f"{field_name} must not be blank")
        _require_timezone(self.created_at, "created_at")
        if self.decided_at is not None:
            _require_timezone(self.decided_at, "decided_at")
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))
        if self.result is not None:
            object.__setattr__(self, "result", MappingProxyType(dict(self.result)))

    def decide(
        self,
        *,
        approved: bool,
        actor_id: str,
        actor_role: ActorRole,
        decided_at: datetime | None = None,
    ) -> "ApprovalRequest":
        if self.status is not ApprovalStatus.PENDING:
            raise DomainValidationError(f"approval is not pending: {self.status}")
        if not actor_id.strip():
            raise DomainValidationError("actor_id must not be blank")
        return replace(
            self,
            status=ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED,
            decided_by=actor_id.strip(),
            decided_role=actor_role,
            decided_at=decided_at or datetime.now(UTC),
        )

    def claim_execution(self) -> "ApprovalRequest":
        if self.status is not ApprovalStatus.APPROVED:
            raise DomainValidationError(f"approval is not executable: {self.status}")
        return replace(self, status=ApprovalStatus.EXECUTING)

    def complete(
        self,
        *,
        result: Mapping[str, object] | None = None,
        error: str | None = None,
    ) -> "ApprovalRequest":
        if self.status is not ApprovalStatus.EXECUTING:
            raise DomainValidationError(f"approval is not executing: {self.status}")
        if (result is None) == (error is None):
            raise DomainValidationError("exactly one of result or error is required")
        return replace(
            self,
            status=ApprovalStatus.EXECUTED if result is not None else ApprovalStatus.FAILED,
            result=result,
            error=error,
        )


def _require_timezone(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{field_name} must include a timezone")
