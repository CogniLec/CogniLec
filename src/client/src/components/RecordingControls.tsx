export interface RecordingControlsProps {
  isRecording: boolean;
  canStart: boolean;
  elapsedMs: number;
  chunkCount: number;
  onStart: () => void;
  onStop: () => void;
}

function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const pad = (n: number): string => n.toString().padStart(2, "0");
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
}

export function RecordingControls({
  isRecording,
  canStart,
  elapsedMs,
  chunkCount,
  onStart,
  onStop,
}: RecordingControlsProps): JSX.Element {
  return (
    <div data-testid="recording-controls" className="flex flex-col items-center gap-4">
      <div className="flex items-center gap-2">
        <span
          className={
            isRecording
              ? "h-2.5 w-2.5 animate-pulse rounded-full bg-rose-500"
              : "h-2.5 w-2.5 rounded-full bg-slate-600"
          }
        />
        <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
          {isRecording ? "Recording" : "Idle"}
        </span>
      </div>

      <div className="font-mono text-4xl font-semibold tabular-nums text-white" data-testid="elapsed-timer">
        {formatElapsed(elapsedMs)}
      </div>

      <div data-testid="chunk-count" className="badge">
        Chunks recorded: {chunkCount}
      </div>

      {isRecording ? (
        <button type="button" onClick={onStop} className="btn-danger w-full max-w-xs">
          Stop Recording
        </button>
      ) : (
        <button type="button" disabled={!canStart} onClick={onStart} className="btn-success w-full max-w-xs">
          Start Recording
        </button>
      )}
    </div>
  );
}
