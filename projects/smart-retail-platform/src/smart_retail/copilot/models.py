"""Structured Copilot answer contracts."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GeneratedCopilotAnswer(BaseModel):
    """Strict model-facing output; citations must be validated against retrieved context."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    citations: list[str]
    insufficient_evidence: bool


@dataclass(frozen=True, slots=True)
class CopilotCitation:
    kind: Literal["knowledge", "tool"]
    citation: str
    source_id: str
    source_version: str
    title: str
    section: str


@dataclass(frozen=True, slots=True)
class CopilotAnswer:
    answer: str
    citations: tuple[CopilotCitation, ...]
    insufficient_evidence: bool
    provider: str
    retrieved_chunks: int
