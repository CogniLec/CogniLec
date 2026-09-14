import { useState } from "react";
import { SubjectPicker } from "./components/SubjectPicker";
import { ConsentGate } from "./components/ConsentGate";
import { RecordingControls } from "./components/RecordingControls";
import { AuthScreen } from "./components/AuthScreen";
import { StudyScreen } from "./components/StudyScreen";
import { useRecorder } from "./hooks/useRecorder";
import { useAuth } from "./hooks/useAuth";
import type { Subject } from "./types";

function CaptureScreen(): JSX.Element {
  const [subject, setSubject] = useState<Subject | null>(null);
  const { appState, elapsedMs, chunkCount, error, consentGiven, acknowledgeConsent, startRecording, stopRecording } =
    useRecorder();

  const isRecording = appState === "RECORDING";
  const canStart = !!subject && consentGiven && !isRecording;

  const handleStart = (): void => {
    if (!subject) return;
    void startRecording(subject.id, subject.name);
  };

  return (
    <div className="flex flex-col gap-6">
      {error && (
        <p role="alert" className="rounded bg-red-100 p-2 text-red-700">
          {error}
        </p>
      )}

      <SubjectPicker selectedSubjectId={subject?.id ?? null} onSelect={setSubject} />

      {!consentGiven && <ConsentGate onAcknowledge={acknowledgeConsent} />}

      <RecordingControls
        isRecording={isRecording}
        canStart={canStart}
        elapsedMs={elapsedMs}
        chunkCount={chunkCount}
        onStart={handleStart}
        onStop={stopRecording}
      />
    </div>
  );
}

export function App(): JSX.Element {
  const { user, loading, login, logout } = useAuth();
  const [tab, setTab] = useState<"capture" | "review">("review");

  if (loading) {
    return <p className="p-6">Loading…</p>;
  }

  if (!user) {
    return <AuthScreen onLogin={login} />;
  }

  return (
    <main className="mx-auto flex max-w-xl flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">LIS</h1>
        <div className="flex items-center gap-3 text-sm">
          <span>{user.email}</span>
          <button type="button" onClick={logout} className="underline">
            Log out
          </button>
        </div>
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setTab("review")}
          className={tab === "review" ? "font-semibold underline" : ""}
        >
          Review
        </button>
        <button
          type="button"
          onClick={() => setTab("capture")}
          className={tab === "capture" ? "font-semibold underline" : ""}
        >
          Capture
        </button>
      </div>

      {tab === "review" ? <StudyScreen /> : <CaptureScreen />}
    </main>
  );
}
