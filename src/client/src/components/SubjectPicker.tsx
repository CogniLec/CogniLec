import { useEffect, useState } from "react";
import { fetchSubjects } from "../services/api";
import type { Subject } from "../types";

export interface SubjectPickerProps {
  selectedSubjectId: string | null;
  onSelect: (subject: Subject) => void;
}

export function SubjectPicker({ selectedSubjectId, onSelect }: SubjectPickerProps): JSX.Element {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchSubjects()
      .then((items) => {
        if (!cancelled) setSubjects(items);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load subjects");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return <p data-testid="subject-picker-loading">Loading subjects…</p>;
  }

  if (error) {
    return (
      <p role="alert" className="text-red-600">
        {error}
      </p>
    );
  }

  if (subjects.length === 0) {
    return <p data-testid="subject-picker-empty">No subjects available. Create one first.</p>;
  }

  return (
    <div data-testid="subject-picker" className="flex flex-col gap-2">
      <label htmlFor="subject-select" className="font-medium">
        Subject
      </label>
      <select
        id="subject-select"
        aria-label="Subject"
        value={selectedSubjectId ?? ""}
        onChange={(event) => {
          const subject = subjects.find((item) => item.id === event.target.value);
          if (subject) onSelect(subject);
        }}
        className="rounded border border-gray-300 p-2"
      >
        <option value="" disabled>
          Select a subject…
        </option>
        {subjects.map((subject) => (
          <option key={subject.id} value={subject.id}>
            {subject.name}
          </option>
        ))}
      </select>
    </div>
  );
}
