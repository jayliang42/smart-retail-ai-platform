"""Small API-key identity boundary for approval-gated operations."""

import hmac
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from smart_retail.domain import ActorRole


@dataclass(frozen=True, slots=True)
class Principal:
    actor_id: str
    role: ActorRole

    def __post_init__(self) -> None:
        if not self.actor_id.strip():
            raise ValueError("actor_id must not be blank")


class _PrincipalConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    actor_id: str = Field(min_length=1, max_length=128)
    role: ActorRole


class ApiKeyAuthenticator:
    """Resolve opaque API keys to server-controlled actor identities and roles."""

    def __init__(self, principals_by_key: Mapping[str, Principal]) -> None:
        if any(not key for key in principals_by_key):
            raise ValueError("API keys must not be blank")
        self._principals_by_key = dict(principals_by_key)

    @classmethod
    def from_json(cls, raw_config: str | None) -> "ApiKeyAuthenticator":
        if not raw_config:
            return cls({})
        parsed = TypeAdapter(dict[str, _PrincipalConfig]).validate_python(
            json.loads(raw_config)
        )
        return cls(
            {
                api_key: Principal(actor_id=config.actor_id, role=config.role)
                for api_key, config in parsed.items()
            }
        )

    @classmethod
    def from_environment(cls) -> "ApiKeyAuthenticator":
        return cls.from_json(os.getenv("SMART_RETAIL_API_KEYS"))

    def authenticate(self, api_key: str | None) -> Principal | None:
        if api_key is None:
            return None
        for expected_key, principal in self._principals_by_key.items():
            if hmac.compare_digest(api_key, expected_key):
                return principal
        return None
