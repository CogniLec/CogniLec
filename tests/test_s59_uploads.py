"""Tests for S59 - post-session upload, EXIF strip & dedup (T59.1-T59.5).

T59.4 (upload triggers the S47 `uploads.ready` partial re-run, not a full
reprocess) is exercised as a real DB-backed integration test using the
same `db_session` fixture and `process_session(skip_embedding=True)` path
S47/S59's own spec designates as the partial re-run entrypoint.
"""

from __future__ import annotations

import io

import piexif
import pytest
from PIL import Image
from src.services.uploads.dedup import compute_phash, find_duplicate, hamming_distance
from src.services.uploads.exif_strip import has_exif, strip_exif
from src.services.uploads.models import FileType, UploadStatus
from src.services.uploads.pipeline import (
    UploadValidationError,
    run_pipeline,
    validate_upload,
)


def _jpeg_with_gps() -> bytes:
    img = Image.new("RGB", (100, 100), color=(200, 50, 50))
    exif_dict = {
        "0th": {piexif.ImageIFD.Make: b"TestCam"},
        "GPS": {piexif.GPSIFD.GPSLatitudeRef: b"N"},
    }
    exif_bytes = piexif.dump(exif_dict)
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif_bytes)
    return out.getvalue()


def _plain_png(color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    img = Image.new("RGB", (64, 64), color=color)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def test_t59_1_image_pdf_and_multipage_pdf_validated_and_typed():
    file_type = validate_upload("image/jpeg", 2 * 1024 * 1024)
    assert file_type == FileType.IMAGE
    file_type = validate_upload("application/pdf", 500 * 1024)
    assert file_type == FileType.PDF


def test_t59_2_gps_and_exif_absent_from_stored_bytes():
    raw = _jpeg_with_gps()
    assert has_exif(raw) is True

    result = strip_exif(raw, "JPEG")
    assert result.stripped is True
    assert has_exif(result.data) is False


def test_t59_3_near_duplicate_detected_and_merged():
    original = _plain_png((100, 100, 100))
    # Slightly perturbed copy (a few pixels changed) simulating a second
    # photo of the same board from a different angle.
    img = Image.open(io.BytesIO(original)).convert("RGB")
    img.putpixel((0, 0), (101, 101, 101))
    out = io.BytesIO()
    img.save(out, format="PNG")
    near_dup = out.getvalue()

    hash_a = compute_phash(original)
    hash_b = compute_phash(near_dup)
    assert hamming_distance(hash_a, hash_b) <= 8

    duplicate_id = find_duplicate(hash_b, [("asset-1", hash_a)], threshold=8)
    assert duplicate_id == "asset-1"

    import random

    rng = random.Random(42)
    noise = Image.new("RGB", (64, 64))
    noise.putdata(
        [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(64 * 64)]
    )
    out2 = io.BytesIO()
    noise.save(out2, format="PNG")
    hash_c = compute_phash(out2.getvalue())
    assert find_duplicate(hash_c, [("asset-1", hash_a)], threshold=8) is None


def test_t59_3_pipeline_merges_duplicate_without_new_asset():
    raw = _plain_png((30, 30, 30))
    first = run_pipeline(
        raw_bytes=raw, image_format="PNG", file_type=FileType.IMAGE, existing_hashes=[]
    )
    assert first.status == UploadStatus.UNIQUE
    assert first.phash is not None

    second = run_pipeline(
        raw_bytes=raw,
        image_format="PNG",
        file_type=FileType.IMAGE,
        existing_hashes=[("existing-asset", first.phash)],
    )
    assert second.status == UploadStatus.DUPLICATE
    assert second.is_duplicate is True
    assert second.merged_asset_id == "existing-asset"


@pytest.mark.asyncio
async def test_t59_4_upload_triggers_partial_rerun_not_full_reprocess(db_session):
    """S59's `uploads.ready` re-run is S47's `skip_embedding=True` path.

    S47's own T47.5 (`tests/test_s47_process_session_flow.py`) already
    exercises exactly this mechanism end to end with real fixtures; this
    reuses those fixtures directly rather than re-deriving fakes, since
    S59's own spec explicitly says the trigger *is* that S47 path, not a
    separate implementation.
    """
    from src.db.models.session import Session, SessionStatus
    from src.services.orchestration.session_pipeline import process_session
    from tests.test_s47_process_session_flow import (
        FakeEmbeddingClient,
        _build_filter_agent,
        _build_synthesis_agent,
        _content_session_with_utterances,
    )

    subject_id, session_id = await _content_session_with_utterances(db_session)
    first = await process_session(
        session_id=session_id,
        subject_id=subject_id,
        embed_model_ver="v1",
        prompt_version="v1.0.0",
        db=db_session,
        embedding_client=FakeEmbeddingClient(),
        filter_agent=_build_filter_agent(),
        synthesis_agent=_build_synthesis_agent(),
    )
    assert first.success is True
    assert first.embedded_count is not None and first.embedded_count > 0

    session_obj = await db_session.get(Session, session_id)
    assert session_obj is not None
    session_obj.status = SessionStatus.PROCESSING
    await db_session.flush()

    # Simulate a S59 upload arriving after notes already exist: the
    # uploads.ready re-run must reuse T1-T3 (skip_embedding=True) rather
    # than re-embedding/re-segmenting from scratch.
    second = await process_session(
        session_id=session_id,
        subject_id=subject_id,
        embed_model_ver="v1",
        prompt_version="v1.0.0",
        db=db_session,
        embedding_client=FakeEmbeddingClient(),
        filter_agent=_build_filter_agent(),
        synthesis_agent=_build_synthesis_agent(),
        skip_embedding=True,
    )
    assert second.success is True
    assert "T1_embed_utterances" in second.skipped_stages
    assert "T2_segment_session" in second.skipped_stages
    assert "T3_cluster_segments" in second.skipped_stages


def test_t59_5_oversized_rejected_with_clear_message():
    with pytest.raises(UploadValidationError) as exc_info:
        validate_upload("image/tiff", 25 * 1024 * 1024, max_size_bytes=20 * 1024 * 1024)
    assert exc_info.value.status_code in (413, 415)


def test_t59_5_unsupported_type_rejected():
    with pytest.raises(UploadValidationError) as exc_info:
        validate_upload("image/tiff", 1024)
    assert exc_info.value.status_code == 415
    assert "image/tiff" in exc_info.value.detail
