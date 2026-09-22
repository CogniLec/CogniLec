import { useRef, useState } from "react";
import { createSession, uploadAudioFile } from "../services/api";
import { friendlyErrorMessage } from "../services/errorMessages";

export interface AudioFileUploadProps {
  subjectId: string;
  onUploaded?: (message: string, sessionId: string) => void;
}

const ACCEPTED_AUDIO_EXTENSIONS = ".mp3,.wav,.m4a,.flac,.ogg,.webm,.aac,.wma,.mp4,.mov,.mkv";

/**
 * Lets a user upload an audio file (MP3, WAV, M4A, FLAC, OGG, WebM, MP4, MOV, MKV) to a
 * new session. Creates a server-side session first, then uploads the file
 * which gets split into 30s chunks and fed into the preprocessing → ASR pipeline.
 */
export function AudioFileUpload({ subjectId, onUploaded }: AudioFileUploadProps): JSX.Element {
  const inputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [progressPct, setProgressPct] = useState<number | null>(null);
  const [uploadedSessionId, setUploadedSessionId] = useState<string | null>(null);

  const handleUpload = async (): Promise<void> => {
    if (!selectedFile) return;
    setUploading(true);
    setProgressPct(0);
    setError(null);
    setResult(null);
    try {
      const session = await createSession(subjectId);
      const response = await uploadAudioFile(session.id, selectedFile, (fraction) =>
        setProgressPct(Math.round(fraction * 100)),
      );
      setResult(response.message);
      setUploadedSessionId(session.id);
      onUploaded?.(response.message, session.id);
      setSelectedFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (err) {
      setError(friendlyErrorMessage(err));
    } finally {
      setUploading(false);
      setProgressPct(null);
    }
  };

  const handleGoToReview = (): void => {
    if (!result || !uploadedSessionId) return;
    onUploaded?.(result, uploadedSessionId);
  };

  return (
    <div className="panel flex flex-col gap-3">
      <div>
        <p className="text-sm font-semibold text-slate-200">Upload audio file</p>
        <p className="text-xs text-slate-500">
          MP3, WAV, M4A, FLAC, OGG, WebM, or video files (MP4, MOV, MKV — audio is extracted) — will be split into chunks and processed automatically.
        </p>
      </div>

      {error && (
        <p role="alert" className="alert-error">
          {error}
        </p>
      )}
      {result && (
        <div className="flex flex-col gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300 sm:flex-row sm:items-center sm:justify-between">
          <span>{result}</span>
          {/* Switching to Review also happens automatically right after
           * upload (via onUploaded above) -- this button is a deliberate,
           * always-available fallback so getting there never depends on
           * that automatic behavior actually firing in a given browser/
           * session. It stays visible until this upload box resets. */}
          <button
            type="button"
            onClick={handleGoToReview}
            className="btn-secondary shrink-0 self-start sm:self-auto"
          >
            Go to Review →
          </button>
        </div>
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
          {uploading
            ? progressPct !== null
              ? `Uploading… ${progressPct}%`
              : "Uploading…"
            : "Upload"}
        </button>
      </div>

      {uploading && progressPct !== null && (
        <div
          data-testid="audio-upload-progress-bar"
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
