from pathlib import Path

import pytest

from smart_retail.knowledge.embedding import HashingEmbeddingProvider
from smart_retail.knowledge.ingestion import ingest_knowledge_manifest
from smart_retail.repositories.base import ResourceAlreadyExistsError
from smart_retail.repositories.memory import InMemoryRetailRepository

KNOWLEDGE_MANIFEST = Path(__file__).parents[1] / "data" / "knowledge" / "manifest.json"


def test_manifest_ingestion_produces_stable_cited_chunks() -> None:
    repository = InMemoryRetailRepository()
    embedder = HashingEmbeddingProvider()

    first = ingest_knowledge_manifest(repository, embedder, KNOWLEDGE_MANIFEST)
    replay = ingest_knowledge_manifest(repository, embedder, KNOWLEDGE_MANIFEST)

    assert len(first) == 3
    assert [item.source for item in replay] == [item.source for item in first]
    assert all(item.chunks for item in first)
    assert all("@v1#" in chunk.citation for item in first for chunk in item.chunks)


def test_retrieval_returns_relevant_source_and_filter() -> None:
    repository = InMemoryRetailRepository()
    embedder = HashingEmbeddingProvider()
    ingest_knowledge_manifest(repository, embedder, KNOWLEDGE_MANIFEST)
    query_embedding = embedder.embed_texts(
        ["verified product remains above 5 for 15 minutes priority one work order"]
    )[0]

    results = repository.search_knowledge(query_embedding, source_ids=None, limit=3)
    filtered = repository.search_knowledge(
        query_embedding,
        source_ids=["refrigeration-manual"],
        limit=3,
    )

    assert results[0].source_id == "refrigeration-manual"
    assert results[0].section == "High-temperature alarm"
    assert filtered
    assert all(result.source_id == "refrigeration-manual" for result in filtered)
    assert results[0].score > 0


def test_source_version_cannot_be_silently_rewritten() -> None:
    repository = InMemoryRetailRepository()
    embedder = HashingEmbeddingProvider()
    ingested = ingest_knowledge_manifest(repository, embedder, KNOWLEDGE_MANIFEST)
    original = ingested[0]
    changed = type(original.source)(
        source_id=original.source.source_id,
        title=original.source.title,
        source_version=original.source.source_version,
        source_uri=original.source.source_uri,
        content=original.source.content + "\nChanged without a new version.",
    )

    with pytest.raises(ResourceAlreadyExistsError, match="different content"):
        repository.ingest_knowledge_source(changed, original.chunks)
