"""Versioned operational knowledge ingestion and retrieval."""

from smart_retail.knowledge.chunking import create_knowledge_chunks
from smart_retail.knowledge.embedding import HashingEmbeddingProvider
from smart_retail.knowledge.models import KnowledgeChunk, KnowledgeSearchResult, KnowledgeSource

__all__ = [
    "HashingEmbeddingProvider",
    "KnowledgeChunk",
    "KnowledgeSearchResult",
    "KnowledgeSource",
    "create_knowledge_chunks",
]
