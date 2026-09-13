"""S25 — async embedding client wrapping TEI (HTTP) or sentence-transformers (local fallback)."""

from __future__ import annotations

import logging
from typing import Literal

import httpx

from src.ml.embedding.versioning import DimensionError, ModelVersionInfo, get_active_version

log = logging.getLogger(__name__)


class EmbeddingClient:
    """Embeds text through TEI when reachable, else falls back to sentence-transformers.

    S25 §5.3 / §6.2: `FALLBACK_LOCAL=True` means a TEI outage degrades the
    service rather than failing every embed call.
    """

    def __init__(
        self,
        tei_base_url: str = "http://tei:80",
        fallback_local: bool = True,
        version_info: ModelVersionInfo | None = None,
        local_device: str = "cpu",
    ) -> None:
        self.tei_base_url = tei_base_url
        self.fallback_local = fallback_local
        self._version_info = version_info
        self._local_model = None
        self._local_device = local_device

    @property
    def version_info(self) -> ModelVersionInfo:
        if self._version_info is None:
            self._version_info = get_active_version()
        return self._version_info

    def _prefix_for(self, task_mode: Literal["retrieval", "clustering"]) -> str:
        info = self.version_info
        return (
            info.instruction_prefix_clustering
            if task_mode == "clustering"
            else info.instruction_prefix_retrieval
        )

    async def embed(
        self,
        texts: list[str],
        task_mode: Literal["retrieval", "clustering"] = "retrieval",
    ) -> list[list[float]]:
        """Embed texts with the appropriate instruction prefix, stamped to the active version."""
        if not texts:
            return []

        prefix = self._prefix_for(task_mode)
        prefixed = [f"{prefix}{t}" for t in texts]

        try:
            vectors = await self._embed_via_tei(prefixed)
        except (httpx.HTTPError, OSError) as exc:
            if not self.fallback_local:
                raise
            log.warning("embedding.fallback_local: TEI unreachable (%s); using local model", exc)
            vectors = self._embed_local(prefixed)

        expected_dim = self.version_info.dim
        for vec in vectors:
            if len(vec) != expected_dim:
                msg = f"Embedding dim {len(vec)} != expected {expected_dim}"
                raise DimensionError(msg)
        return vectors

    async def _embed_via_tei(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(base_url=self.tei_base_url, timeout=30.0) as client:
            resp = await client.post("/embed", json={"inputs": texts})
            resp.raise_for_status()
            return list(resp.json())

    def _embed_local(self, texts: list[str]) -> list[list[float]]:
        if self._local_model is None:
            from src.ml.embedding.embed import load_embedding_model

            self._local_model = load_embedding_model(
                model_name=self.version_info.model, device=self._local_device
            )
        from src.ml.embedding.embed import encode_texts

        arr = encode_texts(self._local_model, texts, normalize=True)
        return list(arr.tolist())

    async def health_check(self) -> bool:
        """Verify the TEI service is reachable and reports the expected dimension."""
        try:
            vectors = await self._embed_via_tei(["health check"])
        except (httpx.HTTPError, OSError):
            return False
        return len(vectors) == 1 and len(vectors[0]) == self.version_info.dim
