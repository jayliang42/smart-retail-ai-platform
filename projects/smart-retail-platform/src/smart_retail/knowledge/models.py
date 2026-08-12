"""Typed knowledge-source and cited retrieval records."""

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class KnowledgeSource:
    source_id: str
    title: str
    source_version: str
    source_uri: str
    content: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (self.source_id, self.title, self.source_version, self.source_uri)
        ):
            raise ValueError("knowledge source metadata cannot be blank")
        if not self.content.strip():
            raise ValueError("knowledge source content cannot be blank")

    @property
    def checksum(self) -> str:
        return sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    chunk_id: str
    source_id: str
    source_version: str
    title: str
    section: str
    ordinal: int
    content: str
    embedding: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("chunk ordinal cannot be negative")
        if not self.content.strip():
            raise ValueError("knowledge chunk content cannot be blank")
        if not self.embedding:
            raise ValueError("knowledge chunk embedding cannot be empty")

    @property
    def citation(self) -> str:
        return f"{self.source_id}@{self.source_version}#{self.chunk_id}"


@dataclass(frozen=True, slots=True)
class KnowledgeSearchResult:
    chunk_id: str
    source_id: str
    source_version: str
    title: str
    section: str
    content: str
    score: float

    @property
    def citation(self) -> str:
        return f"{self.source_id}@{self.source_version}#{self.chunk_id}"
