import { useRef, useState } from "react";
import { uploadMaterial } from "../services/api";

export interface MaterialUploadProps {
  subjectId: string;
}

const ACCEPTED_EXTENSIONS = ".pdf,.png,.jpg,.jpeg,.txt,.md";

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
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const handleUpload = async (): Promise<void> => {
    if (!selectedFile) return;
    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const response = await uploadMaterial(subjectId, selectedFile);
      if (response.status === "failed") {
        setError(response.message);
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
      setError(err instanceof Error ? err.message : "Failed to upload file");
    } finally {
      setUploading(false);
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
        <p className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
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
          {uploading ? "Uploading…" : "Upload"}
        </button>
      </div>
    </div>
  );
}
