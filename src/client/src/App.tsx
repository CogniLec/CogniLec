import { useState } from "react";
import { SubjectPicker } from "./components/SubjectPicker";
import { ConsentGate } from "./components/ConsentGate";
import { RecordingControls } from "./components/RecordingControls";
import { useRecorder } from "./hooks/useRecorder";
import type { Subject } from "./types";

export function App(): JSX.Element {
  const [subject, setSubject] = useState<Subject | null>(null);
  const [consentAcknowledged, setConsentAcknowledged] = useState(false);
  const {
    appState,
    elapsedMs,
    chunkCount,
    error,
    startRecording,
    stopRecording,
  } = useRecorder();

  const isRecording = appState === "RECORDING";
  const canStart = !!subject && consentAcknowledged && !isRecording;

  const handleStart = (): void => {
    if (!subject) return;
    void startRecording(subject.id, subject.name);
  };

  return (
    <main className="mx-auto flex max-w-xl flex-col gap-6 p-6">
      <h1 className="text-xl font-semibold">LIS Lecture Capture</h1>

      {error && (
        <p role="alert" className="rounded bg-red-100 p-2 text-red-700">
          {error}
        </p>
      )}

      <SubjectPicker selectedSubjectId={subject?.id ?? null} onSelect={setSubject} />

      {!consentAcknowledged && (
        <ConsentGate onAcknowledge={() => setConsentAcknowledged(true)} />
      )}

      <RecordingControls
        isRecording={isRecording}
        canStart={canStart}
        elapsedMs={elapsedMs}
        chunkCount={chunkCount}
        onStart={handleStart}
        onStop={stopRecording}
      />
    </main>
  );
}
