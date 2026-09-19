import { useRef, useState } from "react";
import { createSession, uploadAudioFile } from "../services/api";

export interface AudioFileUploadProps {
  subjectId: string;
  onUploaded?: (message: string, sessionId: string) => void;
}

const ACCEPTED_AUDIO_EXTENSIONS = ".mp3,.wav,.m4a,.flac,.ogg,.webm";

/**
 * Lets a user upload an audio file (MP3, WAV, M4A, FLAC, OGG, WebM) to a
 * new session. Creates a server-side session first, then uploads the file
 * which gets split into 30s chunks and fed into the preprocessing → ASR pipeline.
 */
export function AudioFileUpload({ subjectId, onUploaded }: AudioFileUploadProps): JSX.Element {
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
      const session = await createSession(subjectId);
      const response = await uploadAudioFile(session.id, selectedFile);
      setResult(response.message);
      onUploaded?.(response.message, session.id);
      setSelectedFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload audio file");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="panel flex flex-col gap-3">
      <div>
        <p className="text-sm font-semibold text-slate-200">Upload audio file</p>
        <p className="text-xs text-slate-500">
          MP3, WAV, M4A, FLAC, OGG, or WebM — will be split into chunks and processed automatically.
        </p>
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
            aria-label="Choose audio file"
            accept={ACCEPTED_AUDIO_EXTENSIONS}
            className="hidden"
            onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
          />
          <span className="truncate">{selectedFile ? selectedFile.name : "Choose an audio file…"}</span>
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
