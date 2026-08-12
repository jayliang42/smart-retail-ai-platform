"""Embedding provider boundary with a deterministic offline implementation."""

from collections import OrderedDict
from collections.abc import Sequence
from threading import Lock
from typing import ClassVar, Protocol, cast

from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import HashingVectorizer

EMBEDDING_DIMENSIONS = 256


class EmbeddingProvider(Protocol):
    dimensions: int
    name: ClassVar[str]

    def embed_texts(self, texts: Sequence[str]) -> list[tuple[float, ...]]: ...


class HashingEmbeddingProvider:
    """Offline lexical vectors for deterministic tests and local development."""

    dimensions = EMBEDDING_DIMENSIONS
    name: ClassVar[str] = "sklearn_hashing_v1"

    def __init__(self) -> None:
        self._vectorizer = HashingVectorizer(
            n_features=self.dimensions,
            alternate_sign=False,
            norm="l2",
            ngram_range=(1, 2),
        )

    def embed_texts(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        matrix = cast(csr_matrix, self._vectorizer.transform(texts))
        rows = cast(list[list[float]], matrix.toarray().tolist())
        return [tuple(row) for row in rows]


class CachingEmbeddingProvider:
    """Bounded process-local LRU cache for repeated query/document embeddings."""

    name: ClassVar[str] = "bounded_embedding_cache_v1"

    def __init__(self, provider: EmbeddingProvider, *, maximum_entries: int = 2_000) -> None:
        if maximum_entries < 1:
            raise ValueError("maximum_entries must be positive")
        self._provider = provider
        self.dimensions = provider.dimensions
        self._maximum_entries = maximum_entries
        self._cache: OrderedDict[str, tuple[float, ...]] = OrderedDict()
        self._lock = Lock()

    def embed_texts(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        with self._lock:
            missing = list(dict.fromkeys(text for text in texts if text not in self._cache))
            if missing:
                embedded = self._provider.embed_texts(missing)
                if len(embedded) != len(missing):
                    raise RuntimeError("embedding provider returned an unexpected result count")
                for text, vector in zip(missing, embedded, strict=True):
                    self._cache[text] = vector
                    self._cache.move_to_end(text)
                    while len(self._cache) > self._maximum_entries:
                        self._cache.popitem(last=False)
            results: list[tuple[float, ...]] = []
            for text in texts:
                vector = self._cache[text]
                self._cache.move_to_end(text)
                results.append(vector)
            return results
