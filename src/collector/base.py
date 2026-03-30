"""Abstract base collector interface."""

from __future__ import annotations

import abc

from src.storage.models import RawArticle


class BaseCollector(abc.ABC):
    """All collectors must implement collect() returning a list of RawArticle."""

    @abc.abstractmethod
    async def collect(self) -> list[RawArticle]:
        """Fetch and return articles from the source(s)."""
        ...
