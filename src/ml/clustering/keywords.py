"""S31 — c-TF-IDF + KeyBERT keyword extraction per topic cluster."""

from __future__ import annotations

from dataclasses import dataclass

from sklearn.feature_extraction.text import CountVectorizer


@dataclass
class KeywordResult:
    keyword: str
    score: float


def _ctfidf_terms(document: str, n_keywords: int) -> list[KeywordResult]:
    """c-TF-IDF over the single concatenated cluster document (S31 §6.1).

    With one document, TF-IDF's IDF term is constant, so this degenerates to
    a term-frequency ranking - which is exactly c-TF-IDF's behaviour for a
    single class (BERTopic treats each cluster as one "document").
    """
    vectorizer = CountVectorizer(stop_words="english", ngram_range=(1, 2))
    try:
        counts = vectorizer.fit_transform([document])
    except ValueError:
        return []
    terms = vectorizer.get_feature_names_out()
    freqs = counts.toarray()[0]
    ranked = sorted(zip(terms, freqs, strict=True), key=lambda x: -x[1])[:n_keywords]
    max_freq = max((f for _, f in ranked), default=1)
    return [KeywordResult(keyword=t, score=float(f) / float(max_freq)) for t, f in ranked]


def extract_keywords(
    utterance_texts: list[str],
    n_keywords: int = 10,
) -> list[KeywordResult]:
    """Extract keywords for a topic cluster using c-TF-IDF, refined by KeyBERT.

    Falls back to plain c-TF-IDF ranking if KeyBERT is not installed
    (graceful degradation, S31 §6.5 pattern) - the pipeline never fails
    outright over an optional dependency.
    """
    document = " ".join(utterance_texts).strip()
    if not document:
        return []

    ctfidf_results = _ctfidf_terms(document, n_keywords)
    if not ctfidf_results:
        return []

    try:
        from keybert import KeyBERT  # type: ignore[import-not-found]

        candidates = [r.keyword for r in ctfidf_results]
        model = KeyBERT()
        pairs = model.extract_keywords(document, candidates=candidates, top_n=n_keywords)
        return [KeywordResult(keyword=k, score=float(s)) for k, s in pairs]
    except ImportError:
        return ctfidf_results
