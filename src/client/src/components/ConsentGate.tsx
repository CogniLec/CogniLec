import { useState } from "react";

export interface ConsentGateProps {
  onAcknowledge: () => void;
}

/** Blocks recording until the user explicitly acknowledges consent (NFR-S5). */
export function ConsentGate({ onAcknowledge }: ConsentGateProps): JSX.Element {
  const [checked, setChecked] = useState(false);

  return (
    <div
      data-testid="consent-gate"
      className="flex flex-col gap-3 rounded-2xl border border-amber-400/30 bg-amber-400/5 p-5"
    >
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-400/20 text-xs text-amber-300">
          !
        </span>
        <p className="text-sm text-amber-100">
          This session will record audio for lecture transcription. Recording cannot start until you
          acknowledge consent.
        </p>
      </div>
      <label className="flex items-center gap-2.5 text-sm text-amber-50">
        <input
          type="checkbox"
          checked={checked}
          onChange={(event) => setChecked(event.target.checked)}
          aria-label="I consent to being recorded"
          className="h-4 w-4 rounded border-amber-400/40 bg-transparent text-amber-500 focus:ring-amber-400/40"
        />
        I consent to being recorded for this session.
      </label>
      <button
        type="button"
        disabled={!checked}
        onClick={onAcknowledge}
        className="btn self-start bg-amber-500 text-slate-950 hover:bg-amber-400"
      >
        Acknowledge Consent
      </button>
    </div>
  );
}
