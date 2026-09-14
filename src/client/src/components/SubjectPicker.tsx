import { useEffect, useState } from "react";
import { createSubject, fetchSubjects } from "../services/api";
import type { Subject } from "../types";

export interface SubjectPickerProps {
  selectedSubjectId: string | null;
  onSelect: (subject: Subject) => void;
}

export function SubjectPicker({ selectedSubjectId, onSelect }: SubjectPickerProps): JSX.Element {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  const load = (): void => {
    setLoading(true);
    fetchSubjects()
      .then(setSubjects)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load subjects"))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleCreate = async (): Promise<void> => {
    if (!newName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const subject = await createSubject(newName.trim());
      setNewName("");
      load();
      onSelect(subject);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create subject");
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return <p data-testid="subject-picker-loading">Loading subjects…</p>;
  }

  return (
    <div data-testid="subject-picker" className="flex flex-col gap-2">
      {error && (
        <p role="alert" className="text-red-600">
          {error}
        </p>
      )}

      {subjects.length === 0 ? (
        <p data-testid="subject-picker-empty">No subjects available. Create one below.</p>
      ) : (
        <>
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
        </>
      )}

      <div className="flex gap-2">
        <input
          type="text"
          aria-label="New name"
          placeholder="New subject name"
          value={newName}
          onChange={(event) => setNewName(event.target.value)}
          className="flex-1 rounded border border-gray-300 p-2"
        />
        <button
          type="button"
          disabled={!newName.trim() || creating}
          onClick={() => void handleCreate()}
          className="rounded bg-gray-800 px-3 py-1 text-white disabled:opacity-40"
        >
          {creating ? "Creating…" : "Create subject"}
        </button>
      </div>
    </div>
  );
}
