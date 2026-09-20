import { useEffect, useState } from "react";
import { createSubject, fetchSubjects } from "../services/api";
import { friendlyErrorMessage } from "../services/errorMessages";
import type { Subject } from "../types";

export interface SubjectPickerProps {
  selectedSubjectId: string | null;
  onSelect: (subject: Subject) => void;
}

export function SubjectPicker({ selectedSubjectId, onSelect }: SubjectPickerProps): JSX.Element {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Distinguishes a load failure (where "Retry" means "fetch again") from a
  // create failure (where the fix is changing the name, not reloading) --
  // otherwise a duplicate-name error would show a Retry button that just
  // refreshes the list and does nothing to help (docs/gaps.md #33j).
  const [errorSource, setErrorSource] = useState<"load" | "create" | null>(null);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  const load = (): void => {
    setLoading(true);
    setError(null);
    setErrorSource(null);
    fetchSubjects()
      .then(setSubjects)
      .catch((err: unknown) => {
        setError(friendlyErrorMessage(err));
        setErrorSource("load");
      })
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleCreate = async (): Promise<void> => {
    if (!newName.trim()) return;
    setCreating(true);
    setError(null);
    setErrorSource(null);
    try {
      const subject = await createSubject(newName.trim());
      setNewName("");
      load();
      onSelect(subject);
    } catch (err) {
      setError(friendlyErrorMessage(err, { 409: "A subject with that name already exists." }));
      setErrorSource("create");
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return (
      <p data-testid="subject-picker-loading" className="text-sm text-slate-400">
        Loading subjects…
      </p>
    );
  }

  return (
    <div data-testid="subject-picker" className="flex flex-col gap-3">
      {error && (
        <div className="flex items-center gap-2">
          <p role="alert" className="alert-error flex-1">
            {error}
          </p>
          {errorSource === "load" && (
            <button type="button" onClick={load} className="btn-ghost shrink-0 px-3 py-1 text-xs">
              Retry
            </button>
          )}
        </div>
      )}

      {subjects.length === 0 ? (
        <p data-testid="subject-picker-empty" className="text-sm text-slate-400">
          No subjects available. Create one below.
        </p>
      ) : (
        <div className="flex flex-col gap-1.5">
          <label htmlFor="subject-select" className="field-label">
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
            className="text-input"
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
      )}

      <div className="flex gap-2 border-t border-white/5 pt-3">
        <input
          type="text"
          aria-label="New name"
          placeholder="New subject name"
          value={newName}
          onChange={(event) => setNewName(event.target.value)}
          className="text-input flex-1"
        />
        <button
          type="button"
          disabled={!newName.trim() || creating}
          onClick={() => void handleCreate()}
          className="btn-secondary shrink-0"
        >
          {creating ? "Creating…" : "Create subject"}
        </button>
      </div>
    </div>
  );
}
