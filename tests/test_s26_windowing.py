"""Tests for S26 - context-window embedding (T26.1, T26.1b, T26.3, T26.3b)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from src.ml.embedding.windowing import build_windows


@dataclass
class _Utt:
    id: uuid.UUID
    seq: int
    text: str


def _utterances(n: int) -> list[_Utt]:
    return [_Utt(id=uuid.uuid4(), seq=i, text=f"utt{i}") for i in range(n)]


class TestBuildWindows:
    def test_t26_1_start_of_transcript(self) -> None:
        utts = _utterances(10)
        windows = build_windows(utts, W=5)
        assert windows[0].window_size_actual == 1
        assert windows[0].window_text == "utt0"

    def test_t26_1b_end_of_transcript(self) -> None:
        utts = _utterances(10)
        windows = build_windows(utts, W=5)
        assert windows[9].window_size_actual == 5
        assert windows[9].window_text == "utt5 utt6 utt7 utt8 utt9"

    def test_t26_3_isolated_when_w_zero(self) -> None:
        utts = _utterances(10)
        windows = build_windows(utts, W=0)
        assert all(w.window_size_actual == 1 for w in windows)
        assert windows[5].window_text == "utt5"

    def test_t26_3b_shrunk_window(self) -> None:
        utts = _utterances(10)
        windows = build_windows(utts, W=10)
        assert windows[3].window_size_actual == 4

    def test_empty_utterance_list(self) -> None:
        assert build_windows([], W=5) == []

    def test_individual_text_preserved(self) -> None:
        utts = _utterances(5)
        windows = build_windows(utts, W=3)
        for w, u in zip(windows, utts, strict=True):
            assert w.individual_text == u.text
            assert w.utterance_id == u.id
