import { useState } from "react";
import { useStudySession } from "../hooks/useStudySession";
import { ApiError, generateFlashcards } from "../services/api";
import { friendlyErrorMessage } from "../services/errorMessages";
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

// Replaces the old manual "type a flashcard's front/back yourself" form
// (removed 2026-09-17) -- flashcards are now always generated from real
// notes via the LLM, never hand-typed. This button drives that on demand
// for a subject whose auto-generation (which fires after every recording)
// produced nothing yet, or after notes have changed.
function GenerateFlashcardsButton({
  subjectId,
  onGenerated,
}: {
  subjectId: string;
  onGenerated: () => void;
}): JSX.Element {
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async (): Promise<void> => {
    setGenerating(true);
    setError(null);
    try {
      await generateFlashcards(subjectId);
      onGenerated();
    } catch (err) {
      // Previously showed the raw "API request failed: 409 Conflict" for
      // every failure reason -- the backend's actual 409 detail ("no
      // persisted notes/topics yet" vs "generation failed for all of
      // them") is far more actionable, and friendlyErrorMessage's global
      // 409 default ("That already exists") is wrong here (it's tuned for
      // subject-creation's 409, a name collision).
      const detail = err instanceof ApiError ? err.detail : undefined;
      setError(friendlyErrorMessage(err, detail ? { 409: detail } : undefined));
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="panel flex flex-col gap-3">
      {error && (
        <p role="alert" className="alert-error">
          {error}
        </p>
      )}
      <button
        type="button"
        disabled={generating}
        onClick={() => void handleGenerate()}
        className="btn-primary self-start"
      >
        {generating ? "Generating…" : "Generate flashcards from notes"}
      </button>
    </div>
  );
}

export function QuizCard({ subjectId }: QuizCardProps): JSX.Element {
  const { card, loading, error, revealed, reveal, submitReview, refetch } =
    useStudySession(subjectId);
  const [selfCorrect, setSelfCorrect] = useState<boolean | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  if (loading) {
    return (
      <p data-testid="quiz-loading" className="text-sm text-slate-400">
        Loading next card…
      </p>
    );
  }

  if (error || !card) {
    return (
      <div className="flex flex-col gap-3">
        <p data-testid="quiz-empty" className="text-sm text-slate-400">
          {error ?? "No flashcards available for this subject yet."}
        </p>
        <GenerateFlashcardsButton subjectId={subjectId} onGenerated={refetch} />
      </div>
    );
  }

  const handleRate = async (rating: FsrsRating): Promise<void> => {
    if (selfCorrect === null) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await submitReview(rating, selfCorrect);
      setSelfCorrect(null);
    } catch (err) {
      // Previously had no catch at all (docs/gaps.md #33i) -- a network
      // drop mid-submit silently discarded the rating with zero feedback,
      // and `selfCorrect` still got reset in the `finally`, forcing the
      // user to redo their "did you know it" selection with no
      // explanation. Now the error is shown and the selection is kept so
      // retrying is a single click.
      setSubmitError(
        err instanceof Error ? err.message : "Couldn't save your rating — try again.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div data-testid="quiz-card" className="panel flex flex-col gap-4">
      <span className="badge w-fit">{card.topic_label}</span>
      <p className="text-lg font-medium leading-relaxed text-white">{card.front}</p>

      {!revealed && (
        <button type="button" onClick={reveal} className="btn-primary self-start">
          Reveal the actual note
        </button>
      )}

      {revealed && (
        <div className="flex flex-col gap-4">
          <p
            data-testid="quiz-answer"
            className="rounded-lg border border-white/10 bg-slate-950/60 p-3 text-sm leading-relaxed text-slate-200"
          >
            {card.back}
          </p>

          <fieldset className="flex flex-col gap-2 border-t border-white/5 pt-3">
            <legend className="field-label mb-1">Did you actually know this?</legend>
            <label className="flex items-center gap-2 text-sm text-slate-200">
              <input
                type="radio"
                name="self-correct"
                checked={selfCorrect === true}
                onChange={() => setSelfCorrect(true)}
                className="h-4 w-4 border-white/20 bg-transparent text-brand-500 focus:ring-brand-500/40"
              />
              Yes, I knew it
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-200">
              <input
                type="radio"
                name="self-correct"
                checked={selfCorrect === false}
                onChange={() => setSelfCorrect(false)}
                className="h-4 w-4 border-white/20 bg-transparent text-brand-500 focus:ring-brand-500/40"
              />
              No, I got it wrong
            </label>
          </fieldset>

          {submitError && (
            <p role="alert" className="alert-error text-sm">
              {submitError}
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            {RATINGS.map((r) => (
              <button
                key={r.value}
                type="button"
                disabled={selfCorrect === null || submitting}
                onClick={() => void handleRate(r.value)}
                className="btn-secondary"
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
