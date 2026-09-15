import { useState } from "react";
import { SubjectPicker } from "./SubjectPicker";
import { QuizCard } from "./QuizCard";
import { ProgressView } from "./ProgressView";
import type { Subject } from "../types";

export function StudyScreen(): JSX.Element {
  const [subject, setSubject] = useState<Subject | null>(null);
  const [tab, setTab] = useState<"quiz" | "progress">("quiz");

  return (
    <div className="flex flex-col gap-6">
      <section className="panel">
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Subject</h2>
        <SubjectPicker selectedSubjectId={subject?.id ?? null} onSelect={setSubject} />
      </section>

      {subject && (
        <>
          <div className="flex w-fit gap-1 rounded-full border border-white/10 bg-white/5 p-1">
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
          </div>

          {tab === "quiz" ? (
            <QuizCard subjectId={subject.id} />
          ) : (
            <ProgressView subjectId={subject.id} />
          )}
        </>
      )}
    </div>
  );
}
