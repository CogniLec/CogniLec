import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Recorder } from "../services/Recorder";
import { UploadQueue } from "../services/UploadQueue";
import { ChunkStore, SessionStore, enforceQuota } from "../services/db";
import { createSession, uploadSessionChunk } from "../services/api";
import { CONFIG } from "../config";
import type { AppState, RecordingSession, StoredAudioChunk, UploadJob } from "../types";

const MAX_BUFFERED_CHUNKS = 500;

export interface UseRecorderResult {
  appState: AppState;
  session: RecordingSession | null;
  elapsedMs: number;
  chunkCount: number;
  error: string | null;
  consentGiven: boolean;
  requireConsent: () => void;
  acknowledgeConsent: () => void;
  startRecording: (subjectId: string, subjectName: string) => Promise<void>;
  stopRecording: () => void;
  // Chunk upload health -- previously invisible entirely (docs/gaps.md
  // #33i): UploadQueue already emitted `jobUpdated` and exposed
  // `manualRetry`, but nothing subscribed, so a recording could silently
  // fail to sync dozens of chunks with the user none the wiser.
  syncingCount: number;
  failedUploadCount: number;
  retryFailedUploads: () => void;
}

/**
 * Wires Recorder + UploadQueue + IndexedDB together for components.
 * Enforces: no recording without a selected subject (T15.5) and without
 * consent acknowledgement (T15.4).
 */
export function useRecorder(): UseRecorderResult {
  const [appState, setAppState] = useState<AppState>("IDLE");
  const [session, setSession] = useState<RecordingSession | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [chunkCount, setChunkCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [consentGiven, setConsentGiven] = useState(false);

  const recorderRef = useRef<Recorder | null>(null);
  const uploadQueueRef = useRef<UploadQueue | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [uploadJobs, setUploadJobs] = useState<Map<string, UploadJob>>(new Map());

  const getUploadQueue = useCallback((): UploadQueue => {
    if (!uploadQueueRef.current) {
      uploadQueueRef.current = new UploadQueue({
        maxRetries: CONFIG.maxUploadRetries,
        retryBaseMs: CONFIG.uploadRetryBaseMs,
        uploadChunk: uploadSessionChunk,
      });
    }
    return uploadQueueRef.current;
  }, []);

  // Resume any pending uploads left over from a prior tab session (T15.6).
  useEffect(() => {
    void getUploadQueue().resume();
  }, [getUploadQueue]);

  // Track upload health so syncing/failed chunks are visible in the UI
  // instead of silently invisible (docs/gaps.md #33i).
  useEffect(() => {
    const queue = getUploadQueue();
    return queue.on("jobUpdated", (job) => {
      setUploadJobs((prev) => {
        const next = new Map(prev);
        if (job.status === "completed") {
          next.delete(job.id);
        } else {
          next.set(job.id, job);
        }
        return next;
      });
    });
  }, [getUploadQueue]);

  const uploadJobList = useMemo(() => Array.from(uploadJobs.values()), [uploadJobs]);
  const syncingCount = uploadJobList.filter(
    (job) => job.status === "pending" || job.status === "uploading",
  ).length;
  const failedUploadCount = uploadJobList.filter((job) => job.status === "failed").length;

  const retryFailedUploads = useCallback(() => {
    const queue = getUploadQueue();
    for (const job of uploadJobList) {
      if (job.status === "failed") void queue.manualRetry(job.id);
    }
  }, [getUploadQueue, uploadJobList]);

  const requireConsent = useCallback(() => {
    setAppState("CONSENT_REQUIRED");
  }, []);

  const acknowledgeConsent = useCallback(() => {
    setConsentGiven(true);
    setAppState("IDLE");
  }, []);

  const startRecording = useCallback(
    async (subjectId: string, subjectName: string): Promise<void> => {
      setError(null);
      if (!subjectId) {
        setError("A subject must be selected before recording can start.");
        return;
      }
      if (!consentGiven) {
        setAppState("CONSENT_REQUIRED");
        return;
      }
      if (!Recorder.isSupported()) {
        setError("MediaRecorder is not supported in this browser.");
        return;
      }

      // The session must exist server-side before any chunk upload, or
      // every upload is silently rejected (require_owned_session 404s) and
      // no audio ever actually reaches the server, regardless of what the
      // local timer/chunk counter shows -- confirmed live: this was
      // previously a client-only crypto.randomUUID() with no matching
      // backend session at all, so recording looked like it worked but
      // nothing was ever captured server-side.
      let sessionId: string;
      try {
        const created = await createSession(subjectId);
        sessionId = created.id;
      } catch (err) {
        setError(
          err instanceof Error
            ? `Could not start session on the server: ${err.message}`
            : "Could not start session on the server.",
        );
        return;
      }

      const newSession: RecordingSession = {
        id: sessionId,
        subjectId,
        subjectName,
        status: "recording",
        startedAt: Date.now(),
        elapsedMs: 0,
        chunkCount: 0,
        consentAcknowledged: true,
      };
      await SessionStore.put(newSession);
      setSession(newSession);

      const recorder = new Recorder({
        sessionId,
        chunkDurationMs: CONFIG.chunkDurationMs,
        overlapMs: CONFIG.chunkOverlapMs,
      });
      recorderRef.current = recorder;

      recorder.on("chunk", (chunk) => {
        const stored: StoredAudioChunk = { ...chunk, id: `${chunk.sessionId}:${chunk.sequence}` };
        void (async () => {
          await ChunkStore.put(stored, "buffered");
          await enforceQuota(MAX_BUFFERED_CHUNKS);
          setChunkCount((count) => count + 1);
          await getUploadQueue().enqueue(stored);
        })();
      });
      recorder.on("error", (err) => {
        setError(err.message);
      });

      try {
        await recorder.start();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to start recording");
        setAppState("IDLE");
        return;
      }

      setAppState("RECORDING");
      tickRef.current = setInterval(() => {
        setElapsedMs(recorder.getElapsedMs());
      }, 1000);
    },
    [consentGiven, getUploadQueue],
  );

  const stopRecording = useCallback(() => {
    recorderRef.current?.stop();
    recorderRef.current = null;
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
    setAppState("STOPPED");
    setSession((prev) => (prev ? { ...prev, status: "stopped" } : prev));
  }, []);

  useEffect(() => {
    return () => {
      if (tickRef.current) clearInterval(tickRef.current);
    };
  }, []);

  // Closing the tab mid-recording used to silently drop the in-flight
  // MediaRecorder buffer with no warning at all (docs/gaps.md #33i) -- no
  // beforeunload guard existed anywhere in the client.
  useEffect(() => {
    if (appState !== "RECORDING") return;
    const handler = (event: BeforeUnloadEvent): void => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [appState]);

  return {
    appState,
    session,
    elapsedMs,
    chunkCount,
    error,
    consentGiven,
    requireConsent,
    acknowledgeConsent,
    startRecording,
    stopRecording,
    syncingCount,
    failedUploadCount,
    retryFailedUploads,
  };
}
