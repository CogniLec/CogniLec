"""S06 ASR WER utility tests — offline, no GPU required."""

from __future__ import annotations

from src.ml.asr.wer import compute_cer, compute_wer, whisper_normalize


class TestWhisperNormalize:
    def test_lowercase(self):
        assert whisper_normalize("Hello World") == "hello world"

    def test_remove_punctuation(self):
        assert whisper_normalize("Hello, world!") == "hello world"

    def test_remove_extra_spaces(self):
        assert whisper_normalize("hello   world") == "hello world"

    def test_strip_whitespace(self):
        assert whisper_normalize("  hello  ") == "hello"

    def test_empty_string(self):
        assert whisper_normalize("") == ""

    def test_numbers_preserved(self):
        result = whisper_normalize("I have 42 items")
        assert "42" in result

    def test_unicode_passes_through(self):
        result = whisper_normalize("Héllo Wörld")
        assert "héllo" in result or "hello" in result


class TestComputeWer:
    def test_identical_texts(self):
        assert compute_wer("hello world", "hello world") == 0.0

    def test_completely_different(self):
        wer = compute_wer("cat dog", "fish bird")
        assert wer > 0.5

    def test_one_word_difference(self):
        wer = compute_wer("the cat sat", "the dog sat")
        assert 0.0 < wer < 1.0

    def test_no_normalize(self):
        wer = compute_wer("Hello", "hello", normalize=False)
        assert wer > 0.0  # case-sensitive, so different

    def test_normalized_same(self):
        wer = compute_wer("Hello, World!", "hello world")
        assert wer == 0.0

    def test_empty_both(self):
        assert compute_wer("", "") == 0.0

    def test_empty_reference(self):
        wer = compute_wer("", "hello")
        assert wer == 1.0


class TestComputeCer:
    def test_identical(self):
        assert compute_cer("abc", "abc") == 0.0

    def test_one_char_off(self):
        cer = compute_cer("abc", "axc")
        assert 0.0 < cer < 1.0

    def test_completely_different(self):
        cer = compute_cer("aaa", "bbb")
        assert cer == 1.0

    def test_empty_both(self):
        assert compute_cer("", "") == 0.0

    def test_normalized_match(self):
        cer = compute_cer("Hello, World!", "hello world")
        assert cer == 0.0
