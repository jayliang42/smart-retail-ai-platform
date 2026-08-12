"""Authenticated actor and immutable operation-audit records."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from smart_retail.domain.approvals import ActorRole
from smart_retail.domain.inventory import DomainValidationError


@dataclass(frozen=True, slots=True)
class AuditActor:
    actor_id: str
    role: ActorRole

    def __post_init__(self) -> None:
        if not self.actor_id.strip():
            raise DomainValidationError("actor_id must not be blank")


@dataclass(frozen=True, slots=True)
class OperationAuditEvent:
    actor: AuditActor
    action: str
    resource_type: str
    resource_id: str
    request_id: str | None = None
    event_id: str = field(default_factory=lambda: f"audit-{uuid4().hex}")
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        for field_name in ("event_id", "action", "resource_type", "resource_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise DomainValidationError(f"{field_name} must not be blank")
        if self.request_id is not None and not self.request_id.strip():
            raise DomainValidationError("request_id must not be blank when provided")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise DomainValidationError("occurred_at must include a timezone")
