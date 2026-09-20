import { useRef, useState } from "react";
import { uploadMaterial } from "../services/api";
import { friendlyErrorMessage } from "../services/errorMessages";

export interface MaterialUploadProps {
  subjectId: string;
}

const ACCEPTED_EXTENSIONS = ".pdf,.png,.jpg,.jpeg,.txt,.md";
// Matches the server's real cap (src/api/routes/syllabus_upload.py
// MAX_UPLOAD_SIZE_BYTES) -- checking client-side rejects an oversize file
// instantly instead of after a full upload round-trip that, with no
// progress indicator, looks like a hang (docs/gaps.md #33j).
const MAX_UPLOAD_SIZE_BYTES = 20 * 1024 * 1024;

/**
 * Lets a user attach reference material (syllabus, textbook page, board
 * photo, notes) to a subject — PDF, image, TXT, or MD, matching what
 * src/services/docling/parser.py `detect_format` actually accepts
 * (src/api/routes/syllabus_upload.py). Separate from flashcard creation:
 * this feeds the syllabus-extraction pipeline (S51), not a direct Q&A pair.
 */
export function MaterialUpload({ subjectId }: MaterialUploadProps): JSX.Element {
  const inputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progressPct, setProgressPct] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  // Distinguishes a real extraction from `items_extracted: 0` (a scanned
  // or otherwise unparseable file) -- these used to render in the exact
  // same green "success" box (docs/gaps.md #33i), so a user skimming the
  // page had no way to tell their upload actually extracted nothing.
  const [resultIsWarning, setResultIsWarning] = useState(false);

  const handleUpload = async (): Promise<void> => {
    if (!selectedFile) return;
    if (selectedFile.size > MAX_UPLOAD_SIZE_BYTES) {
      setError(`That file is too large. The limit is ${MAX_UPLOAD_SIZE_BYTES / (1024 * 1024)}MB.`);
      return;
    }
    setUploading(true);
    setProgressPct(0);
    setError(null);
    setResult(null);
    setResultIsWarning(false);
    try {
      const response = await uploadMaterial(subjectId, selectedFile, (fraction) =>
        setProgressPct(Math.round(fraction * 100)),
      );
      if (response.status === "failed") {
        setError(response.message);
      } else if (response.items_extracted === 0) {
        setResultIsWarning(true);
        setResult(
          `${response.message} — no content could be extracted from this file. It may be scanned or unparseable.`,
        );
      } else {
        setResult(
          response.items_extracted !== null
            ? `${response.message} (${response.items_extracted} item${response.items_extracted === 1 ? "" : "s"} extracted)`
            : response.message,
        );
      }
      setSelectedFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      setError(friendlyErrorMessage(err));
    } finally {
      setUploading(false);
      setProgressPct(null);
    }
  };

  return (
    <div className="panel flex flex-col gap-3">
      <div>
        <p className="text-sm font-semibold text-slate-200">Add material</p>
        <p className="text-xs text-slate-500">Syllabus, textbook pages, board photos, or notes — PDF, image, TXT, or MD.</p>
      </div>

      {error && (
        <p role="alert" className="alert-error">
          {error}
        </p>
      )}
      {result && (
        <p
          data-testid="material-upload-result"
          data-variant={resultIsWarning ? "warning" : "success"}
          className={
            resultIsWarning
              ? "rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-300"
              : "rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300"
          }
        >
          {result}
        </p>
      )}

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <label className="text-input flex flex-1 cursor-pointer items-center gap-2 text-slate-400">
          <input
            ref={inputRef}
            type="file"
            aria-label="Choose file"
            accept={ACCEPTED_EXTENSIONS}
            className="hidden"
            onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
          />
          <span className="truncate">{selectedFile ? selectedFile.name : "Choose a file…"}</span>
        </label>
        <button
          type="button"
          disabled={!selectedFile || uploading}
          onClick={() => void handleUpload()}
          className="btn-secondary shrink-0"
        >
          {uploading
            ? progressPct !== null
              ? `Uploading… ${progressPct}%`
              : "Uploading…"
            : "Upload"}
        </button>
      </div>

      {uploading && progressPct !== null && (
        <div
          data-testid="upload-progress-bar"
          data-progress={progressPct}
          className="h-1.5 w-full overflow-hidden rounded-full bg-white/10"
        >
          <div
            className="h-full rounded-full bg-brand-500 transition-all"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      )}
    </div>
  );
}
