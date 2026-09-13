"""S62 — common licence-filtered image source client interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.services.image_retrieval.models import RetrievedImage


class ImageSourceClient(ABC):
    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[RetrievedImage]:
        """Search this source for images matching `query`."""

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this source's API is reachable."""
