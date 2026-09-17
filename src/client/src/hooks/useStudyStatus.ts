import { useEffect, useRef, useState } from "react";
import { fetchStudyStatus } from "../services/api";
import type { StudyStatus } from "../types";

const POLL_INTERVAL_MS = 15_000;

// Recording-to-flashcard processing measured at ~15-20 minutes for a real
// lecture (docs/gaps.md #33f); stop polling well past the worker's own
// 30-minute asyncio.wait_for ceiling (src/workers/asr_worker.py) so a
// truly stuck session doesn't poll forever.
const MAX_POLL_MS = 35 * 60 * 1000;

export interface UseStudyStatusResult {
  status: StudyStatus | null;
  isProcessing: boolean;
}

/**
 * Polls `/study/status` while a subject's most recent recording is still
 * being transcribed/processed, so the UI can show a "Generating your
 * notes..." banner instead of the user having to manually reload the
 * Review tab to discover flashcards exist (docs/gaps.md #33f).
 */
export function useStudyStatus(subjectId: string | null): UseStudyStatusResult {
  const [status, setStatus] = useState<StudyStatus | null>(null);
  const startedAtRef = useRef<number>(Date.now());

  useEffect(() => {
    if (!subjectId) {
      setStatus(null);
      return;
    }
    setStatus(null);
    startedAtRef.current = Date.now();
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
    const interval = setInterval(() => {
      if (Date.now() - startedAtRef.current > MAX_POLL_MS) {
        clearInterval(interval);
        return;
      }
      poll();
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [subjectId]);

  const isProcessing =
    status !== null &&
    !status.notes_ready &&
    status.status !== "failed" &&
    status.status !== null;

  return { status, isProcessing };
}
