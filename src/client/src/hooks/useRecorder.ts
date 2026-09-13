import { useCallback, useEffect, useRef, useState } from "react";
import { Recorder } from "../services/Recorder";
import { UploadQueue } from "../services/UploadQueue";
import { ChunkStore, SessionStore, enforceQuota } from "../services/db";
import { fetchPresignedUploadUrl, uploadChunkToPresignedUrl } from "../services/api";
import { CONFIG } from "../config";
import type { AppState, RecordingSession, StoredAudioChunk } from "../types";

const MAX_BUFFERED_CHUNKS = 500;

export interface UseRecorderResult {
  appState: AppState;
  session: RecordingSession | null;
  elapsedMs: number;
  chunkCount: number;
  error: string | null;
  requireConsent: () => void;
  acknowledgeConsent: () => void;
  startRecording: (subjectId: string, subjectName: string) => Promise<void>;
  stopRecording: () => void;
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

  const getUploadQueue = useCallback((): UploadQueue => {
    if (!uploadQueueRef.current) {
      uploadQueueRef.current = new UploadQueue({
        maxRetries: CONFIG.maxUploadRetries,
        retryBaseMs: CONFIG.uploadRetryBaseMs,
        getPresignedUrl: fetchPresignedUploadUrl,
        uploadChunk: uploadChunkToPresignedUrl,
      });
    }
    return uploadQueueRef.current;
  }, []);

  // Resume any pending uploads left over from a prior tab session (T15.6).
  useEffect(() => {
    void getUploadQueue().resume();
  }, [getUploadQueue]);

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

      const sessionId = crypto.randomUUID();
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

  return {
    appState,
    session,
    elapsedMs,
    chunkCount,
    error,
    requireConsent,
    acknowledgeConsent,
    startRecording,
    stopRecording,
  };
}
