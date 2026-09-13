import { useState } from "react";
import { useStudySession } from "../hooks/useStudySession";
import type { FsrsRating } from "../types";

export interface QuizCardProps {
  subjectId: string;
}

const RATINGS: { value: FsrsRating; label: string }[] = [
  { value: 1, label: "Again" },
  { value: 2, label: "Hard" },
  { value: 3, label: "Good" },
  { value: 4, label: "Easy" },
];

export function QuizCard({ subjectId }: QuizCardProps): JSX.Element {
  const { card, loading, error, revealed, reveal, submitReview } = useStudySession(subjectId);
  const [selfCorrect, setSelfCorrect] = useState<boolean | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (loading) {
    return <p data-testid="quiz-loading">Loading next card…</p>;
  }

  if (error || !card) {
    return (
      <p data-testid="quiz-empty" className="text-gray-600">
        {error ?? "No flashcards available for this subject yet."}
      </p>
    );
  }

  const handleRate = async (rating: FsrsRating): Promise<void> => {
    if (selfCorrect === null) return;
    setSubmitting(true);
    try {
      await submitReview(rating, selfCorrect);
    } finally {
      setSubmitting(false);
      setSelfCorrect(null);
    }
  };

  return (
    <div data-testid="quiz-card" className="flex flex-col gap-4 rounded border p-4">
      <p className="text-xs uppercase text-gray-500">{card.topic_label}</p>
      <p className="text-lg font-medium">{card.front}</p>

      {!revealed && (
        <button
          type="button"
          onClick={reveal}
          className="self-start rounded bg-gray-800 px-3 py-1 text-white"
        >
          Reveal the actual note
        </button>
      )}

      {revealed && (
        <div className="flex flex-col gap-3">
          <p data-testid="quiz-answer" className="rounded bg-gray-100 p-2">
            {card.back}
          </p>

          <fieldset className="flex flex-col gap-1">
            <legend>Did you actually know this?</legend>
            <label>
              <input
                type="radio"
                name="self-correct"
                checked={selfCorrect === true}
                onChange={() => setSelfCorrect(true)}
              />{" "}
              Yes, I knew it
            </label>
            <label>
              <input
                type="radio"
                name="self-correct"
                checked={selfCorrect === false}
                onChange={() => setSelfCorrect(false)}
              />{" "}
              No, I got it wrong
            </label>
          </fieldset>

          <div className="flex gap-2">
            {RATINGS.map((r) => (
              <button
                key={r.value}
                type="button"
                disabled={selfCorrect === null || submitting}
                onClick={() => void handleRate(r.value)}
                className="rounded border px-2 py-1 disabled:opacity-40"
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
