"""S58 — study material export: Markdown, DOCX (pandoc), PDF (Typst), Anki (genanki).

Markdown is generated directly, in-process, with no external binary. DOCX
shells out to the real system `pandoc` binary (present in this environment
- `shutil.which("pandoc")`). PDF export is written for real against the
spec's Typst backend, but no `typst` binary exists anywhere in this sandbox
(checked via `shutil.which` and a filesystem search) - see docs/gaps.md
new gap for the missing binary; `pdf_available()` reports this so callers
(and tests) can detect it rather than silently producing nothing.

KaTeX/Mermaid "rendering" for Markdown output means passing `$...$`/
` ```mermaid ``` ` blocks through unchanged - a Markdown viewer (GitHub,
Obsidian, etc.) renders both natively from that syntax; there is no
separate rendering step for the Markdown path itself.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import genanki


@dataclass(frozen=True)
class FlashcardExportItem:
    front: str
    back: str


@dataclass(frozen=True)
class NoteExportSection:
    heading: str
    body_md: str


def pandoc_available() -> bool:
    return shutil.which("pandoc") is not None


def typst_available() -> bool:
    return shutil.which("typst") is not None


def render_markdown(title: str, sections: list[NoteExportSection]) -> str:
    """Render notes as Markdown. KaTeX (`$...$`) and Mermaid fences pass through
    verbatim - GitHub/Obsidian-style Markdown renderers interpret both natively."""
    parts = [f"# {title}\n"]
    for section in sections:
        parts.append(f"## {section.heading}\n\n{section.body_md}\n")
    return "\n".join(parts)


def export_markdown(title: str, sections: list[NoteExportSection], out_path: Path) -> Path:
    out_path.write_text(render_markdown(title, sections), encoding="utf-8")
    return out_path


class DocxExportError(Exception):
    pass


def export_docx(title: str, sections: list[NoteExportSection], out_path: Path) -> Path:
    """Convert the same Markdown to DOCX via a real `pandoc` subprocess call."""
    if not pandoc_available():
        msg = "pandoc binary not found on PATH"
        raise DocxExportError(msg)
    markdown = render_markdown(title, sections)
    proc = subprocess.run(
        ["pandoc", "--from=markdown", "--to=docx", "--output", str(out_path)],
        input=markdown,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        msg = f"pandoc failed: {proc.stderr}"
        raise DocxExportError(msg)
    return out_path


class PdfExportError(Exception):
    pass


def export_pdf_via_typst(title: str, sections: list[NoteExportSection], out_path: Path) -> Path:
    """Render notes to a `.typ` source and compile it with `typst compile`.

    Raises `PdfExportError` if the `typst` binary isn't available - callers
    should check `typst_available()` first (or catch this) rather than
    assume PDF export always succeeds in every environment.
    """
    if not typst_available():
        msg = "typst binary not found on PATH"
        raise PdfExportError(msg)
    typ_source = _render_typst(title, sections)
    typ_path = out_path.with_suffix(".typ")
    typ_path.write_text(typ_source, encoding="utf-8")
    proc = subprocess.run(
        ["typst", "compile", str(typ_path), str(out_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        msg = f"typst compile failed: {proc.stderr}"
        raise PdfExportError(msg)
    return out_path


def _render_typst(title: str, sections: list[NoteExportSection]) -> str:
    lines = [f"= {title}"]
    for section in sections:
        lines.append(f"== {section.heading}")
        lines.append(section.body_md)
    return "\n\n".join(lines)


_ANKI_MODEL_ID = 1607392319
_ANKI_MODEL = genanki.Model(
    _ANKI_MODEL_ID,
    "LIS Basic",
    fields=[{"name": "Front"}, {"name": "Back"}],
    templates=[
        {
            "name": "Card 1",
            "qfmt": "{{Front}}",
            "afmt": '{{FrontSide}}<hr id="answer">{{Back}}',
        }
    ],
)


def export_anki(
    deck_name: str, deck_id: int, cards: list[FlashcardExportItem], out_path: Path
) -> Path:
    """Build a real `.apkg` package from `cards` via genanki."""
    deck = genanki.Deck(deck_id, deck_name)
    for card in cards:
        deck.add_note(genanki.Note(model=_ANKI_MODEL, fields=[card.front, card.back]))
    genanki.Package(deck).write_to_file(str(out_path))
    return out_path
