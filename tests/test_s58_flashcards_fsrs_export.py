"""Tests for S58 - flashcards, FSRS scheduling, and export (T58.1-T58.6).

T58.5's PDF half (Typst) and T58.6's real Anki import are addressed
honestly rather than faked:
  - No `typst` binary exists anywhere in this sandbox (checked via
    `shutil.which` and a filesystem search) - see docs/gaps.md's new gap
    for Block 10. Markdown and DOCX (via the real system `pandoc` binary,
    which IS present) are both genuinely exercised below.
  - T58.6 ("imports successfully into Anki") needs the actual Anki
    application, which isn't installable here; what's genuinely testable
    is that `genanki.Package.write_to_file` produces a well-formed
    `.apkg` (a real zip containing a valid `collection.anki2` sqlite DB)
    - that structural validity is checked directly instead of driving a
    real Anki import.
"""

from __future__ import annotations

import sqlite3
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fsrs import Card, Rating, Scheduler
from src.db.models.flashcard import Flashcard
from src.services.study import fsrs_scheduler
from src.services.study.export import (
    FlashcardExportItem,
    NoteExportSection,
    export_anki,
    export_docx,
    export_markdown,
    pandoc_available,
    typst_available,
)
from src.services.study.flashcards import (
    group_reviews_by_topic,
    weighted_topic_selection,
)

PDF_SKIP_REASON = (
    "No `typst` binary is installed anywhere in this sandbox (docs/gaps.md "
    "new gap #10) - PDF export code is implemented for real against Typst "
    "but cannot be exercised here without the compiler."
)


def make_flashcard(**overrides) -> Flashcard:
    defaults = fsrs_scheduler.new_card_fields()
    fc = Flashcard(
        id=uuid.uuid4(),
        subject_id=uuid.uuid4(),
        topic_label="Newton's Laws",
        front="What is F = ma?",
        back="Force equals mass times acceleration",
        **defaults,
    )
    for k, v in overrides.items():
        setattr(fc, k, v)
    return fc


def test_t58_1_flashcards_have_valid_qa_pairs():
    from src.services.study.flashcards import GeneratedFlashcard

    card = GeneratedFlashcard(front="What is Newton's second law?", back="F = m * a")
    assert card.front
    assert card.back


def test_t58_2_fsrs_scheduling_matches_reference_py_fsrs():
    """`fsrs_scheduler.review` must produce byte-for-byte the same result as
    calling the real `py-fsrs` `Scheduler` directly on an equivalent `Card` -
    it's a thin field-mapping wrapper around the reference implementation,
    not a reimplementation (see the module docstring)."""
    fixed_now = datetime(2026, 1, 1, tzinfo=UTC)
    review_sequence = [Rating.Good, Rating.Again, Rating.Easy, Rating.Hard, Rating.Good]

    reference_scheduler = Scheduler(enable_fuzzing=False)
    reference_card = Card()
    fc = make_flashcard(**fsrs_scheduler._card_to_fields(reference_card))

    t = fixed_now
    for rating in review_sequence:
        reference_card, _ = reference_scheduler.review_card(
            reference_card, rating, review_datetime=t
        )
        updated_fields = fsrs_scheduler.review(fc, rating, review_datetime=t)
        for k, v in updated_fields.items():
            setattr(fc, k, v)
        t = t + timedelta(days=1)

    assert fc.fsrs_state == int(reference_card.state)
    assert fc.fsrs_step == reference_card.step
    assert fc.fsrs_stability == pytest.approx(reference_card.stability)
    assert fc.fsrs_difficulty == pytest.approx(reference_card.difficulty)
    assert fc.due_at == reference_card.due
    assert fc.last_review_at == reference_card.last_review


def test_t58_3_review_persisted_influences_subsequent_scheduling():
    fc = make_flashcard()
    due_before = fc.due_at

    updated = fsrs_scheduler.review(
        fc, Rating.Good, review_datetime=datetime(2026, 1, 1, tzinfo=UTC)
    )
    for k, v in updated.items():
        setattr(fc, k, v)
    due_after_first = fc.due_at
    assert due_after_first != due_before  # the review changed the schedule

    updated_again = fsrs_scheduler.review(fc, Rating.Again, review_datetime=due_after_first)
    for k, v in updated_again.items():
        setattr(fc, k, v)
    # A second, different-rated review starting from the post-first-review
    # state produces yet another distinct due date - state genuinely carries
    # forward between reviews rather than resetting.
    assert fc.due_at != due_after_first


def test_t58_4_question_selection_weights_toward_poorly_performing_topics():
    reviews = [
        ("weak_topic", False),
        ("weak_topic", False),
        ("weak_topic", True),
        ("strong_topic", True),
        ("strong_topic", True),
        ("strong_topic", True),
    ]
    performances = group_reviews_by_topic(reviews)
    allocation = weighted_topic_selection(performances, total_slots=10)

    assert allocation["weak_topic"] > allocation["strong_topic"]
    assert sum(allocation.values()) == 10


def test_t58_5_markdown_and_docx_exports_produce_valid_files(tmp_path: Path):
    sections = [
        NoteExportSection(
            heading="Kinematics",
            body_md="Velocity is $v = \\frac{dx}{dt}$.\n\n```mermaid\ngraph TD; A-->B;\n```",
        )
    ]
    md_path = export_markdown("Physics Notes", sections, tmp_path / "notes.md")
    assert md_path.exists()
    content = md_path.read_text()
    assert "$v = \\frac{dx}{dt}$" in content  # KaTeX syntax preserved
    assert "```mermaid" in content  # Mermaid fence preserved

    assert pandoc_available(), "pandoc must be on PATH in this environment for a real DOCX check"
    docx_path = export_docx("Physics Notes", sections, tmp_path / "notes.docx")
    assert docx_path.exists()
    assert docx_path.stat().st_size > 0
    with zipfile.ZipFile(docx_path) as zf:
        assert "word/document.xml" in zf.namelist()  # a genuine OOXML package


@pytest.mark.skipif(not typst_available(), reason=PDF_SKIP_REASON)
def test_t58_5_pdf_export_via_typst(tmp_path: Path):
    from src.services.study.export import export_pdf_via_typst

    sections = [NoteExportSection(heading="Kinematics", body_md="Velocity is v = dx/dt.")]
    pdf_path = export_pdf_via_typst("Physics Notes", sections, tmp_path / "notes.pdf")
    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF")


def test_t58_6_anki_apkg_is_a_well_formed_package(tmp_path: Path):
    cards = [
        FlashcardExportItem(front="What is F=ma?", back="Newton's second law"),
        FlashcardExportItem(front="What is v=d/t?", back="Definition of velocity"),
    ]
    apkg_path = export_anki("Physics Deck", 998877, cards, tmp_path / "deck.apkg")
    assert apkg_path.exists()

    with zipfile.ZipFile(apkg_path) as zf:
        names = zf.namelist()
        db_name = "collection.anki21" if "collection.anki21" in names else "collection.anki2"
        assert db_name in names
        zf.extract(db_name, tmp_path)

    con = sqlite3.connect(tmp_path / db_name)
    try:
        cur = con.execute("SELECT count(*) FROM notes")
        assert cur.fetchone()[0] == 2
    finally:
        con.close()
