import { useEffect, useState } from "react";
import { fetchStudyProgress } from "../services/api";
import type { StudyProgress } from "../types";

export interface ProgressViewProps {
  subjectId: string;
}

export function ProgressView({ subjectId }: ProgressViewProps): JSX.Element {
  const [progress, setProgress] = useState<StudyProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchStudyProgress(subjectId)
      .then((data) => {
        if (!cancelled) setProgress(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load progress");
      });
    return () => {
      cancelled = true;
    };
  }, [subjectId]);

  if (error) {
    return (
      <p role="alert" className="alert-error">
        {error}
      </p>
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

      {progress.recent_outcomes.length > 0 && (
        <div className="panel">
          <p className="field-label mb-3">Recent activity</p>
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
        </div>
      )}
    </div>
  );
}
