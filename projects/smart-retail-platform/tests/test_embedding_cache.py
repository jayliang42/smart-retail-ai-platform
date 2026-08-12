from collections.abc import Sequence
from typing import ClassVar

from smart_retail.knowledge.embedding import CachingEmbeddingProvider


class _CountingEmbeddingProvider:
    dimensions = 1
    name: ClassVar[str] = "counting_test_provider"

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def embed_texts(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        self.calls.append(tuple(texts))
        return [(float(len(text)),) for text in texts]


def test_embedding_cache_reuses_values_and_preserves_input_order() -> None:
    provider = _CountingEmbeddingProvider()
    cache = CachingEmbeddingProvider(provider, maximum_entries=2)

    first = cache.embed_texts(["milk", "sensor", "milk"])
    second = cache.embed_texts(["sensor", "milk"])

    assert first == [(4.0,), (6.0,), (4.0,)]
    assert second == [(6.0,), (4.0,)]
    assert provider.calls == [("milk", "sensor")]


def test_embedding_cache_evicts_least_recently_used_value() -> None:
    provider = _CountingEmbeddingProvider()
    cache = CachingEmbeddingProvider(provider, maximum_entries=2)
    cache.embed_texts(["one", "two"])
    cache.embed_texts(["one"])

    cache.embed_texts(["three"])
    cache.embed_texts(["two"])

    assert provider.calls == [("one", "two"), ("three",), ("two",)]
