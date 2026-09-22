import { useEffect, useRef, useState } from "react";
import { SubjectPicker } from "./SubjectPicker";
import { QuizCard } from "./QuizCard";
import { ProgressView } from "./ProgressView";
import { MaterialUpload } from "./MaterialUpload";
import { useStudyStatus } from "../hooks/useStudyStatus";
import type { Subject } from "../types";

function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function StudyScreen(): JSX.Element {
  const [subject, setSubject] = useState<Subject | null>(null);
  const [tab, setTab] = useState<"quiz" | "progress" | "materials">("quiz");
  const { status, isProcessing, elapsedMs, progressFraction } = useStudyStatus(subject?.id ?? null);

  // Forces QuizCard to remount (and refetch) the moment generation
  // finishes, since the user may be sitting on the quiz tab the whole
  // time and would otherwise never see the freshly-generated cards
  // without a manual reload (docs/gaps.md #33f).
  const [refreshToken, setRefreshToken] = useState(0);
  const wasProcessingRef = useRef(false);
  useEffect(() => {
    if (wasProcessingRef.current && !isProcessing && status?.notes_ready) {
      setRefreshToken((n) => n + 1);
    }
    wasProcessingRef.current = isProcessing;
  }, [isProcessing, status?.notes_ready]);

  return (
    <div className="flex flex-col gap-6">
      <section className="panel rise-in">
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Subject</h2>
        <SubjectPicker selectedSubjectId={subject?.id ?? null} onSelect={setSubject} />
      </section>

      {subject && (
        <>
          {isProcessing && (
            <div
              data-testid="study-status-banner"
              className="panel rise-in flex flex-col gap-3 border-brand-500/30 bg-brand-500/10 text-sm text-slate-200"
            >
              <div className="flex items-center gap-3">
                <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-brand-400" />
                <span>
                  Generating your notes and flashcards from the latest recording — this can take
                  15-20 minutes. This page will update automatically.
                </span>
              </div>
              <div className="flex items-center gap-3">
                <div
                  data-testid="study-status-progress-bar"
                  data-progress={Math.round(progressFraction * 100)}
                  className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/10"
                >
                  <div
                    className="h-full rounded-full bg-brand-500 transition-all"
                    style={{ width: `${Math.round(progressFraction * 100)}%` }}
                  />
                </div>
                <span data-testid="study-status-elapsed" className="shrink-0 text-xs text-slate-400">
                  {formatElapsed(elapsedMs)} elapsed
                </span>
              </div>
            </div>
          )}
          {status?.status === "failed" && (
            <div
              data-testid="study-status-failed"
              className="panel rise-in border-red-500/30 bg-red-500/10 text-sm text-slate-200"
            >
              The last recording failed to generate notes{status.failure_reason ? `: ${status.failure_reason}` : "."}
              {" "}Try the &quot;Generate flashcards from notes&quot; button below, or record again.
            </div>
          )}

          <div className="rise-in flex w-fit gap-1 rounded-full border border-white/10 bg-white/5 p-1">
            <button
              type="button"
              onClick={() => setTab("quiz")}
              className={tab === "quiz" ? "pill-tab-active" : "pill-tab"}
            >
              Quiz
            </button>
            <button
              type="button"
              onClick={() => setTab("progress")}
              className={tab === "progress" ? "pill-tab-active" : "pill-tab"}
            >
              Progress
            </button>
            <button
              type="button"
              onClick={() => setTab("materials")}
              className={tab === "materials" ? "pill-tab-active" : "pill-tab"}
            >
              Materials
            </button>
          </div>

          <div key={`${tab}-${refreshToken}`} className="rise-in">
            {tab === "quiz" && <QuizCard subjectId={subject.id} />}
            {tab === "progress" && <ProgressView subjectId={subject.id} />}
            {tab === "materials" && <MaterialUpload subjectId={subject.id} />}
          </div>
        </>
      )}
    </div>
  );
}
