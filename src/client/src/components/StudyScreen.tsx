import { useState } from "react";
import { SubjectPicker } from "./SubjectPicker";
import { QuizCard } from "./QuizCard";
import { ProgressView } from "./ProgressView";
import type { Subject } from "../types";

export function StudyScreen(): JSX.Element {
  const [subject, setSubject] = useState<Subject | null>(null);
  const [tab, setTab] = useState<"quiz" | "progress">("quiz");

  return (
    <div className="flex flex-col gap-4">
      <SubjectPicker selectedSubjectId={subject?.id ?? null} onSelect={setSubject} />

      {subject && (
        <>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setTab("quiz")}
              className={tab === "quiz" ? "font-semibold underline" : ""}
            >
              Quiz
            </button>
            <button
              type="button"
              onClick={() => setTab("progress")}
              className={tab === "progress" ? "font-semibold underline" : ""}
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
