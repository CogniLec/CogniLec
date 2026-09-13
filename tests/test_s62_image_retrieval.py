"""Tests for S62 - licensed image retrieval & scoring (T62.1-T62.6).

T62.3 (precision@1 > 0.70 on 200 labelled concept/image pairs against a
real CLIP model) needs a GPU-loaded CLIP model this sandbox does not have
(gap #2) — an honest skip. Every other test is genuinely run: source
clients are exercised via `httpx.MockTransport` (no outbound internet
access exists here — confirmed, `api.openverse.org` times out), and the
composite scorer/licence filter/attribution logic is real.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest
from src.services.image_retrieval.attribution import format_attribution
from src.services.image_retrieval.licence import LicenceAcceptance, LicenceCategory, check_licence
from src.services.image_retrieval.models import ImageAsset, ImageSource, RetrievedImage
from src.services.image_retrieval.scorer import CompositeScorer
from src.services.image_retrieval.sources.openverse import SOURCE, OpenverseClient


def _image(licence: LicenceCategory, title: str = "Human Heart Anatomy") -> RetrievedImage:
    return RetrievedImage(
        id="1",
        source=ImageSource(name="wikimedia", base_url="https://commons.wikimedia.org"),
        source_url="https://commons.wikimedia.org/wiki/File:x.svg",
        image_url="https://upload.wikimedia.org/x.svg",
        title=title,
        licence=licence,
        licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
        author="OpenStax",
    )


@pytest.mark.asyncio
async def test_t62_1_retrieval_returns_only_openly_licensed_results():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "a1",
                        "title": "Nebula formation",
                        "foreign_landing_url": "https://openverse.org/a1",
                        "url": "https://img/a1.jpg",
                        "license": "by",
                        "license_url": "https://creativecommons.org/licenses/by/4.0/",
                        "creator": "NASA",
                    },
                    {
                        "id": "a2",
                        "title": "Restricted photo",
                        "foreign_landing_url": "https://openverse.org/a2",
                        "url": "https://img/a2.jpg",
                        "license": "by-nc-nd",
                        "creator": "someone",
                    },
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = OpenverseClient(
        client=httpx.AsyncClient(transport=transport, base_url=SOURCE.base_url)
    )
    images = await client.search("nebula")

    accepted = [img for img in images if check_licence(img.licence) == LicenceAcceptance.ACCEPTED]
    rejected = [img for img in images if check_licence(img.licence) != LicenceAcceptance.ACCEPTED]
    assert len(accepted) == 1
    assert accepted[0].licence == LicenceCategory.CC_BY
    assert len(rejected) == 1
    assert rejected[0].licence == LicenceCategory.CC_BY_NC_ND


def test_t62_2_every_used_image_has_source_url_and_licence():
    asset = ImageAsset(
        note_section_id=uuid.uuid4(),
        source_url="https://commons.wikimedia.org/wiki/File:x.svg",
        licence=LicenceCategory.CC_BY_SA,
        image_url="https://upload.wikimedia.org/x.svg",
        composite_score=0.8,
    )
    assert asset.source_url
    assert asset.licence is not None


@pytest.mark.skip(
    reason="T62.3: needs a real GPU-loaded CLIP model and a 200-pair labelled "
    "concept/image test set to honestly measure precision@1. No GPU-loaded "
    "CLIP model exists in this sandbox (docs/gaps.md gap #2)."
)
def test_t62_3_precision_at_1_above_0_70(): ...


def test_t62_4_below_threshold_routes_to_generation():
    scorer = CompositeScorer(clip_align_fn=lambda c, i: 0.1)
    img = _image(LicenceCategory.CC_BY_SA, title="totally unrelated caption text")
    result = scorer.score("microscopic structure of a neuron", img)
    assert result is not None
    assert result.accepted is False
    assert result.composite_score < 0.50


def test_t62_4_restricted_licence_never_scored():
    scorer = CompositeScorer(clip_align_fn=lambda c, i: 0.99)
    img = _image(LicenceCategory.CC_BY_NC_ND)
    assert scorer.score("human heart anatomy", img) is None


def test_t62_5_attribution_visible_and_formatted():
    asset = ImageAsset(
        note_section_id=uuid.uuid4(),
        source_url="https://commons.wikimedia.org/wiki/File:x.svg",
        licence=LicenceCategory.CC_BY_SA,
        image_url="https://upload.wikimedia.org/x.svg",
        composite_score=0.8,
        author="OpenStax",
    )
    text = format_attribution(asset, "Human Heart Anatomy")
    assert "Human Heart Anatomy" in text
    assert "OpenStax" in text
    assert "CC BY SA" in text


def test_t62_6_no_general_web_image_search_endpoint_exists():
    """Code-search assertion (T62.6): no Google/Bing/SerpAPI-style general
    web image search client exists anywhere in `src/`."""
    src_root = Path(__file__).resolve().parents[1] / "src"
    banned_patterns = (
        "googleapis.com/customsearch",
        "bing.microsoft.com/v7.0/images",
        "serpapi.com",
        "google_images",
        "bing_image_search",
    )
    for path in src_root.rglob("*.py"):
        contents = path.read_text().lower()
        for pattern in banned_patterns:
            assert pattern not in contents, f"found banned pattern {pattern!r} in {path}"
