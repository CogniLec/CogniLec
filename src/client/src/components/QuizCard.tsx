import { useState } from "react";
import { useStudySession } from "../hooks/useStudySession";
import { seedFlashcard } from "../services/api";
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

function AddFlashcardForm({
  subjectId,
  onAdded,
}: {
  subjectId: string;
  onAdded: () => void;
}): JSX.Element {
  const [topicLabel, setTopicLabel] = useState("");
  const [front, setFront] = useState("");
  const [back, setBack] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSave = topicLabel.trim() && front.trim() && back.trim() && !saving;

  const handleAdd = async (): Promise<void> => {
    setSaving(true);
    setError(null);
    try {
      await seedFlashcard(subjectId, topicLabel.trim(), front.trim(), back.trim());
      setTopicLabel("");
      setFront("");
      setBack("");
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add flashcard");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-2 rounded border p-3">
      <p className="font-medium">Add a flashcard</p>
      {error && (
        <p role="alert" className="text-red-600">
          {error}
        </p>
      )}
      <input
        type="text"
        aria-label="Topic"
        placeholder="Topic (e.g. Cell Biology)"
        value={topicLabel}
        onChange={(event) => setTopicLabel(event.target.value)}
        className="rounded border border-gray-300 p-2"
      />
      <input
        type="text"
        aria-label="Question"
        placeholder="Question"
        value={front}
        onChange={(event) => setFront(event.target.value)}
        className="rounded border border-gray-300 p-2"
      />
      <textarea
        aria-label="Answer"
        placeholder="Answer"
        value={back}
        onChange={(event) => setBack(event.target.value)}
        className="rounded border border-gray-300 p-2"
      />
      <button
        type="button"
        disabled={!canSave}
        onClick={() => void handleAdd()}
        className="self-start rounded bg-gray-800 px-3 py-1 text-white disabled:opacity-40"
      >
        {saving ? "Adding…" : "Add flashcard"}
      </button>
    </div>
  );
}

export function QuizCard({ subjectId }: QuizCardProps): JSX.Element {
  const { card, loading, error, revealed, reveal, submitReview, refetch } =
    useStudySession(subjectId);
  const [selfCorrect, setSelfCorrect] = useState<boolean | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (loading) {
    return <p data-testid="quiz-loading">Loading next card…</p>;
  }

  if (error || !card) {
    return (
      <div className="flex flex-col gap-3">
        <p data-testid="quiz-empty" className="text-gray-600">
          {error ?? "No flashcards available for this subject yet."}
        </p>
        <AddFlashcardForm subjectId={subjectId} onAdded={refetch} />
      </div>
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
