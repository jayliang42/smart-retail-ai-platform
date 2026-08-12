"""Retail persistence implementations."""

from smart_retail.repositories.base import RetailRepository
from smart_retail.repositories.memory import InMemoryRetailRepository

__all__ = ["InMemoryRetailRepository", "RetailRepository"]
