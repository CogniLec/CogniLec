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
    <div data-testid="recording-controls" className="flex flex-col gap-3">
      <div className="text-2xl font-mono" data-testid="elapsed-timer">
        {formatElapsed(elapsedMs)}
      </div>
      <div data-testid="chunk-count" className="text-sm text-gray-500">
        Chunks recorded: {chunkCount}
      </div>
      {isRecording ? (
        <button
          type="button"
          onClick={onStop}
          className="rounded bg-red-600 px-4 py-2 text-white"
        >
          Stop Recording
        </button>
      ) : (
        <button
          type="button"
          disabled={!canStart}
          onClick={onStart}
          className="rounded bg-green-600 px-4 py-2 text-white disabled:opacity-40"
        >
          Start Recording
        </button>
      )}
    </div>
  );
}
