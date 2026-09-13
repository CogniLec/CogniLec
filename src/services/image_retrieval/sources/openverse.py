"""S62 — Openverse (CC-licensed media search) client.

No outbound internet access exists in this sandbox (confirmed: `api.openverse.org`
times out — only the package index allowlist is reachable), so this client
is exercised in tests via `httpx.MockTransport`, the same injection point
`RerankerClient` (S54) uses for its own unreachable-in-sandbox backend.
"""

from __future__ import annotations

import httpx
from src.services.image_retrieval.licence import LicenceCategory
from src.services.image_retrieval.models import ImageSource, RetrievedImage
from src.services.image_retrieval.sources.base import ImageSourceClient

_LICENCE_MAP = {
    "cc0": LicenceCategory.CC0,
    "by": LicenceCategory.CC_BY,
    "by-sa": LicenceCategory.CC_BY_SA,
    "by-nd": LicenceCategory.CC_BY_ND,
    "by-nc": LicenceCategory.CC_BY_NC,
    "by-nc-sa": LicenceCategory.CC_BY_NC_SA,
    "by-nc-nd": LicenceCategory.CC_BY_NC_ND,
    "pdm": LicenceCategory.PDM,
}

SOURCE = ImageSource(name="openverse", base_url="https://api.openverse.org/v1")


class OpenverseClient(ImageSourceClient):
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(base_url=SOURCE.base_url, timeout=10.0)

    def is_available(self) -> bool:
        return True

    async def search(self, query: str, limit: int = 10) -> list[RetrievedImage]:
        try:
            response = await self._client.get("/images/", params={"q": query, "page_size": limit})
            response.raise_for_status()
        except (httpx.HTTPError, OSError):
            return []
        payload = response.json()
        results: list[RetrievedImage] = []
        for item in payload.get("results", []):
            licence = _LICENCE_MAP.get(item.get("license", "").lower(), LicenceCategory.UNKNOWN)
            results.append(
                RetrievedImage(
                    id=str(item.get("id")),
                    source=SOURCE,
                    source_url=item.get("foreign_landing_url", ""),
                    image_url=item.get("url", ""),
                    title=item.get("title", ""),
                    licence=licence,
                    licence_url=item.get("license_url"),
                    author=item.get("creator"),
                    width=item.get("width"),
                    height=item.get("height"),
                    thumbnail_url=item.get("thumbnail"),
                )
            )
        return results
