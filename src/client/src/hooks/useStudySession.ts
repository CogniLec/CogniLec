import { useCallback, useEffect, useState } from "react";
import { fetchNextFlashcard, reviewFlashcard } from "../services/api";
import type { Flashcard, FsrsRating } from "../types";

export interface UseStudySessionResult {
  card: Flashcard | null;
  loading: boolean;
  error: string | null;
  revealed: boolean;
  reveal: () => void;
  submitReview: (rating: FsrsRating, selfCorrect: boolean) => Promise<void>;
  refetch: () => void;
}

/**
 * Drives one subject's review loop: fetch the next due flashcard, let the
 * caller reveal the real note/answer, submit the outcome (FSRS rating +
 * self-assessed correctness), then load the next card.
 */
export function useStudySession(subjectId: string | null): UseStudySessionResult {
  const [card, setCard] = useState<Flashcard | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revealed, setRevealed] = useState(false);

  const loadNext = useCallback(() => {
    if (!subjectId) return;
    setLoading(true);
    setError(null);
    setRevealed(false);
    fetchNextFlashcard(subjectId)
      .then(setCard)
      .catch((err: unknown) => {
        setCard(null);
        setError(err instanceof Error ? err.message : "No flashcards available");
      })
      .finally(() => setLoading(false));
  }, [subjectId]);

  useEffect(() => {
    loadNext();
  }, [loadNext]);

  const reveal = useCallback(() => setRevealed(true), []);

  const submitReview = useCallback(
    async (rating: FsrsRating, selfCorrect: boolean) => {
      if (!subjectId || !card) return;
      await reviewFlashcard(subjectId, card.id, rating, selfCorrect, true);
      loadNext();
    },
    [subjectId, card, loadNext],
  );

  return { card, loading, error, revealed, reveal, submitReview, refetch: loadNext };
}
