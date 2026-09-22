import { useEffect, useRef, useState } from "react";
import { fetchStudyStatus } from "../services/api";
import type { StudyStatus } from "../types";

const POLL_INTERVAL_MS = 15_000;

// Recording-to-flashcard processing measured at ~15-20 minutes for a real
// lecture (docs/gaps.md #33f); stop polling well past the worker's own
// 30-minute asyncio.wait_for ceiling (src/workers/asr_worker.py) so a
// truly stuck session doesn't poll forever.
const MAX_POLL_MS = 35 * 60 * 1000;

// Same measured range the processing banner already quoted (docs/gaps.md
// #33f) -- used here to turn elapsed time into a progress fraction. It's a
// rough estimate, not a real per-stage ETA (the backend doesn't expose
// one), so the fraction is capped below 100% until notes_ready actually
// flips true rather than implying a precision we don't have.
const ESTIMATE_MS = 17.5 * 60 * 1000;
const MAX_DISPLAYED_FRACTION = 0.95;

export interface UseStudyStatusResult {
  status: StudyStatus | null;
  isProcessing: boolean;
  /** ms since this hook started watching the current subject/session. Resets
   * to 0 if the component watching it unmounts and remounts (e.g. leaving
   * and returning to the Review tab), not tied to the session's real start
   * time server-side -- an approximation, not an authoritative clock. */
  elapsedMs: number;
  /** Rough [0, MAX_DISPLAYED_FRACTION] progress estimate toward ESTIMATE_MS. */
  progressFraction: number;
}

/**
 * Polls `/study/status` while a subject's most recent recording is still
 * being transcribed/processed, so the UI can show a "Generating your
 * notes..." banner instead of the user having to manually reload the
 * Review tab to discover flashcards exist (docs/gaps.md #33f).
 */
export function useStudyStatus(subjectId: string | null): UseStudyStatusResult {
  const [status, setStatus] = useState<StudyStatus | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const startedAtRef = useRef<number>(Date.now());

  useEffect(() => {
    if (!subjectId) {
      setStatus(null);
      return;
    }
    setStatus(null);
    startedAtRef.current = Date.now();
    setElapsedMs(0);
    let cancelled = false;

    const poll = (): void => {
      fetchStudyStatus(subjectId)
        .then((result) => {
          if (!cancelled) setStatus(result);
        })
        .catch(() => {
          // Transient failure -- just try again next tick.
        });
    };

    poll();
    const pollInterval = setInterval(() => {
      if (Date.now() - startedAtRef.current > MAX_POLL_MS) {
        clearInterval(pollInterval);
        return;
      }
      poll();
    }, POLL_INTERVAL_MS);
    // Separate, faster tick just for the displayed elapsed time/progress
    // bar so it visibly moves between polls instead of jumping every 15s.
    const clockInterval = setInterval(() => {
      setElapsedMs(Date.now() - startedAtRef.current);
    }, 1000);

    return () => {
      cancelled = true;
      clearInterval(pollInterval);
      clearInterval(clockInterval);
    };
  }, [subjectId]);

  const isProcessing =
    status !== null &&
    !status.notes_ready &&
    status.status !== "failed" &&
    status.status !== null;

  const progressFraction = isProcessing
    ? Math.min(elapsedMs / ESTIMATE_MS, MAX_DISPLAYED_FRACTION)
    : 0;

  return { status, isProcessing, elapsedMs, progressFraction };
}
