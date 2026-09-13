import { useState } from "react";

export interface ConsentGateProps {
  onAcknowledge: () => void;
}

/** Blocks recording until the user explicitly acknowledges consent (NFR-S5). */
export function ConsentGate({ onAcknowledge }: ConsentGateProps): JSX.Element {
  const [checked, setChecked] = useState(false);

  return (
    <div data-testid="consent-gate" className="flex flex-col gap-3 rounded border border-amber-400 p-4">
      <p>
        This session will record audio for lecture transcription. Recording cannot start until you
        acknowledge consent.
      </p>
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={checked}
          onChange={(event) => setChecked(event.target.checked)}
          aria-label="I consent to being recorded"
        />
        I consent to being recorded for this session.
      </label>
      <button
        type="button"
        disabled={!checked}
        onClick={onAcknowledge}
        className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-40"
      >
        Acknowledge Consent
      </button>
    </div>
  );
}
