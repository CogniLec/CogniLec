"""Optional LLM judge (different model family from the local synthesizer).

Off by default: it sends transcript excerpts and card text off-machine, which
cuts against the self-hosted default (ADR-018). Fails open -- any error yields
None so scoring records the term as unscored and never blocks the pipeline.
"""

from __future__ import annotations

import json
import logging

import httpx

log = logging.getLogger(__name__)


class Judge:
    def __init__(self, base_url: str, api_key: str, model: str, client: httpx.Client | None = None):
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._key = api_key
        self._model = model
        self._client = client or httpx.Client(timeout=60.0)

    def supported(self, claim: str, source: str) -> bool | None:
        """Is `claim` fully supported by `source`? None if the judge failed."""
        prompt = (
            "Source excerpt:\n"
            + source
            + "\n\nClaim:\n"
            + claim
            + "\n\nIs the claim fully supported by the excerpt? "
            'Answer JSON only: {"supported": true|false}'
        )
        try:
            r = self._client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}"},
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                },
            )
            r.raise_for_status()
            return bool(json.loads(r.json()["choices"][0]["message"]["content"])["supported"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.warning("quality judge failed (%s); term left unscored", exc)
            return None
