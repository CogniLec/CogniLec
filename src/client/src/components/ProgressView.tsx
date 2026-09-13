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
      <p role="alert" className="text-red-600">
        {error}
      </p>
    );
  }

  if (!progress) {
    return <p data-testid="progress-loading">Loading progress…</p>;
  }

  return (
    <div data-testid="progress-view" className="flex flex-col gap-2">
      <p>Total reviews: {progress.total_reviews}</p>
      <p>Accuracy: {Math.round(progress.accuracy * 100)}%</p>
      <ul className="flex flex-col gap-1">
        {progress.recent_outcomes.map((outcome, index) => (
          <li key={`${outcome.flashcard_id}-${index}`} className="text-sm text-gray-700">
            {new Date(outcome.reviewed_at).toLocaleString()} — rating {outcome.rating}
          </li>
        ))}
      </ul>
    </div>
  );
}
