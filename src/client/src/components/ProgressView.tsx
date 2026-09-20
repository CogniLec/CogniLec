import { useCallback, useEffect, useState } from "react";
import { fetchStudyProgress } from "../services/api";
import { friendlyErrorMessage } from "../services/errorMessages";
import type { StudyProgress } from "../types";

export interface ProgressViewProps {
  subjectId: string;
}

export function ProgressView({ subjectId }: ProgressViewProps): JSX.Element {
  const [progress, setProgress] = useState<StudyProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);

  const retry = useCallback((): void => setRetryToken((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchStudyProgress(subjectId)
      .then((data) => {
        if (!cancelled) setProgress(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(friendlyErrorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [subjectId, retryToken]);

  if (error) {
    return (
      <div className="flex items-center gap-2">
        <p role="alert" className="alert-error flex-1">
          {error}
        </p>
        <button type="button" onClick={retry} className="btn-ghost shrink-0 px-3 py-1 text-xs">
          Retry
        </button>
      </div>
    );
  }

  if (!progress) {
    return (
      <p data-testid="progress-loading" className="text-sm text-slate-400">
        Loading progress…
      </p>
    );
  }

  const accuracyPct = Math.round(progress.accuracy * 100);

  return (
    <div data-testid="progress-view" className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="panel">
          <p className="field-label">Total reviews</p>
          <p className="mt-1 text-2xl font-semibold text-white">{progress.total_reviews}</p>
        </div>
        <div className="panel">
          <p className="field-label">Accuracy</p>
          <p className="mt-1 text-2xl font-semibold text-white">{accuracyPct}%</p>
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full rounded-full bg-brand-500 transition-all"
              style={{ width: `${accuracyPct}%` }}
            />
          </div>
        </div>
      </div>

      <div className="panel">
        <p className="field-label mb-3">Recent activity</p>
        {progress.recent_outcomes.length > 0 ? (
          <ul className="flex flex-col divide-y divide-white/5">
            {progress.recent_outcomes.map((outcome, index) => (
              <li
                key={`${outcome.flashcard_id}-${index}`}
                className="flex items-center justify-between py-2 text-sm text-slate-300"
              >
                <span>{new Date(outcome.reviewed_at).toLocaleString()}</span>
                <span className="badge">rating {outcome.rating}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p data-testid="progress-no-activity" className="text-sm text-slate-500">
            No reviews yet — start studying a subject's flashcards to see your activity here.
          </p>
        )}
      </div>
    </div>
  );
}
