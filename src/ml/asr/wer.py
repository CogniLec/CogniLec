"""ASR evaluation utilities — WER, CER, and text normalization."""

from __future__ import annotations

import jiwer


def whisper_normalize(text: str) -> str:
    """Normalize text using jiwer's Whisper-compatible normalizer.

    Applies: strip -> remove multiple spaces -> remove punctuation -> lowercase.
    """
    return jiwer.ToLowerCase()(
        jiwer.RemovePunctuation()(jiwer.RemoveMultipleSpaces()(text.strip()))
    )


def compute_wer(reference: str, hypothesis: str, normalize: bool = True) -> float:
    """Compute Word Error Rate between reference and hypothesis.

    Args:
        reference: ground-truth transcript
        hypothesis: ASR output
        normalize: apply whisper_normalize to both texts

    Returns:
        WER as a float in [0, 1+]
    """
    if normalize:
        reference = whisper_normalize(reference)
        hypothesis = whisper_normalize(hypothesis)
    if not reference and not hypothesis:
        return 0.0
    if not reference:
        return 1.0  # reference empty, any hypothesis is wrong
    return jiwer.wer(reference, hypothesis)


def compute_cer(reference: str, hypothesis: str, normalize: bool = True) -> float:
    """Compute Character Error Rate between reference and hypothesis.

    Args:
        reference: ground-truth transcript
        hypothesis: ASR output
        normalize: apply whisper_normalize to both texts

    Returns:
        CER as a float in [0, 1+]
    """
    if normalize:
        reference = whisper_normalize(reference)
        hypothesis = whisper_normalize(hypothesis)
    if not reference and not hypothesis:
        return 0.0
    if not reference:
        return 1.0
    return jiwer.cer(reference, hypothesis)
