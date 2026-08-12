"""Manifest-driven ingestion for versioned operational Markdown sources."""

import argparse
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from smart_retail.knowledge.chunking import create_knowledge_chunks
from smart_retail.knowledge.embedding import EmbeddingProvider, HashingEmbeddingProvider
from smart_retail.knowledge.models import KnowledgeChunk, KnowledgeSource
from smart_retail.repositories.base import RetailRepository


class _ManifestEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    path: str = Field(min_length=1)
    source_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    source_version: str = Field(min_length=1, max_length=64)
    source_uri: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True, slots=True)
class IngestedKnowledgeSource:
    source: KnowledgeSource
    chunks: tuple[KnowledgeChunk, ...]


def load_knowledge_manifest(manifest_path: Path) -> list[KnowledgeSource]:
    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = TypeAdapter(list[_ManifestEntry]).validate_python(raw_manifest)
    sources: list[KnowledgeSource] = []
    for entry in entries:
        content_path = manifest_path.parent / entry.path
        sources.append(
            KnowledgeSource(
                source_id=entry.source_id,
                title=entry.title,
                source_version=entry.source_version,
                source_uri=entry.source_uri,
                content=content_path.read_text(encoding="utf-8"),
            )
        )
    return sources


def ingest_knowledge_manifest(
    repository: RetailRepository,
    embedder: EmbeddingProvider,
    manifest_path: Path,
) -> list[IngestedKnowledgeSource]:
    ingested: list[IngestedKnowledgeSource] = []
    for source in load_knowledge_manifest(manifest_path):
        chunks = tuple(create_knowledge_chunks(source, embedder))
        persisted = repository.ingest_knowledge_source(source, chunks)
        ingested.append(IngestedKnowledgeSource(source=persisted, chunks=chunks))
    return ingested


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest versioned operational knowledge")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    database_url = cast(str | None, args.database_url)
    if not database_url:
        raise SystemExit("DATABASE_URL or --database-url is required to persist knowledge")

    from smart_retail.repositories.postgres import (
        PostgresRetailRepository,
        build_session_factory,
    )

    repository = PostgresRetailRepository(build_session_factory(database_url))
    ingested = ingest_knowledge_manifest(
        repository,
        HashingEmbeddingProvider(),
        cast(Path, args.manifest),
    )
    output = {
        "sources": [
            {
                "source_id": item.source.source_id,
                "source_version": item.source.source_version,
                "checksum": item.source.checksum,
                "chunks": len(item.chunks),
            }
            for item in ingested
        ]
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
