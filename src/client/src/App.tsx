import { useState } from "react";
import { SubjectPicker } from "./components/SubjectPicker";
import { ConsentGate } from "./components/ConsentGate";
import { RecordingControls } from "./components/RecordingControls";
import { AuthScreen } from "./components/AuthScreen";
import { StudyScreen } from "./components/StudyScreen";
import { FloatingBackdrop } from "./components/FloatingBackdrop";
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
        <p role="alert" className="alert-error rise-in">
          {error}
        </p>
      )}

      <section className="panel rise-in" style={{ animationDelay: "40ms" }}>
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Subject</h2>
        <SubjectPicker selectedSubjectId={subject?.id ?? null} onSelect={setSubject} />
      </section>

      {!consentGiven && (
        <div className="rise-in" style={{ animationDelay: "80ms" }}>
          <ConsentGate onAcknowledge={acknowledgeConsent} />
        </div>
      )}

      <section className="panel rise-in flex flex-col items-center gap-4 text-center" style={{ animationDelay: "120ms" }}>
        <RecordingControls
          isRecording={isRecording}
          canStart={canStart}
          elapsedMs={elapsedMs}
          chunkCount={chunkCount}
          onStart={handleStart}
          onStop={stopRecording}
        />
      </section>
    </div>
  );
}

export function App(): JSX.Element {
  const { user, loading, login, logout } = useAuth();
  const [tab, setTab] = useState<"capture" | "review">("review");

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-400">
        <FloatingBackdrop />
        <p className="animate-pulse text-sm">Loading…</p>
      </div>
    );
  }

  if (!user) {
    return (
      <>
        <FloatingBackdrop />
        <AuthScreen onLogin={login} />
      </>
    );
  }

  return (
    <>
      <FloatingBackdrop />
      <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-6 px-4 py-8 sm:px-6">
        <header className="rise-in flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-sm font-bold text-white shadow-panel">
              N
            </span>
            <div>
              <h1 className="text-lg font-semibold leading-tight text-white">Notely</h1>
              <p className="text-xs text-slate-500">Topic-first study companion</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-slate-400 sm:inline">{user.email}</span>
            <button type="button" onClick={logout} className="btn-ghost">
              Log out
            </button>
          </div>
        </header>

        <nav className="rise-in flex w-fit gap-1 rounded-full border border-white/10 bg-white/5 p-1">
          <button
            type="button"
            onClick={() => setTab("review")}
            className={tab === "review" ? "pill-tab-active" : "pill-tab"}
          >
            Review
          </button>
          <button
            type="button"
            onClick={() => setTab("capture")}
            className={tab === "capture" ? "pill-tab-active" : "pill-tab"}
          >
            Capture
          </button>
        </nav>

        {tab === "review" ? <StudyScreen /> : <CaptureScreen />}
      </main>
    </>
  );
}
