import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StudyScreen } from "../../../src/client/src/components/StudyScreen";
import * as api from "../../../src/client/src/services/api";

vi.mock("../../../src/client/src/components/SubjectPicker", () => ({
  SubjectPicker: ({
    onSelect,
  }: {
    onSelect: (subject: { id: string; name: string; description: string | null }) => void;
  }): JSX.Element => (
    <button type="button" onClick={() => onSelect({ id: "subj-1", name: "Subj", description: null })}>
      pick-subject
    </button>
  ),
}));

describe("StudyScreen study-status polling banner (docs/gaps.md #33f)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a generating banner while the latest session is still processing", async () => {
    vi.spyOn(api, "fetchStudyStatus").mockResolvedValue({
      subject_id: "subj-1",
      session_id: "sess-1",
      status: "processing",
      notes_ready: false,
      flashcard_count: 0,
      failure_reason: null,
    });
    vi.spyOn(api, "fetchNextFlashcard").mockRejectedValue(
      Object.assign(new Error("404"), { status: 404 }),
    );

    render(<StudyScreen />);
    await userEvent.click(screen.getByText("pick-subject"));

    await waitFor(() => expect(screen.getByTestId("study-status-banner")).toBeInTheDocument());
    expect(screen.getByTestId("study-status-banner")).toHaveTextContent(
      "Generating your notes and flashcards",
    );
  });

  it("shows a failure banner when the latest session failed", async () => {
    vi.spyOn(api, "fetchStudyStatus").mockResolvedValue({
      subject_id: "subj-1",
      session_id: "sess-1",
      status: "failed",
      notes_ready: false,
      flashcard_count: 0,
      failure_reason: "LLM router exhausted",
    });
    vi.spyOn(api, "fetchNextFlashcard").mockRejectedValue(
      Object.assign(new Error("404"), { status: 404 }),
    );

    render(<StudyScreen />);
    await userEvent.click(screen.getByText("pick-subject"));

    await waitFor(() => expect(screen.getByTestId("study-status-failed")).toBeInTheDocument());
    expect(screen.getByTestId("study-status-failed")).toHaveTextContent("LLM router exhausted");
  });

  it("shows no banner once notes are ready", async () => {
    vi.spyOn(api, "fetchStudyStatus").mockResolvedValue({
      subject_id: "subj-1",
      session_id: "sess-1",
      status: "complete",
      notes_ready: true,
      flashcard_count: 5,
      failure_reason: null,
    });
    vi.spyOn(api, "fetchNextFlashcard").mockRejectedValue(
      Object.assign(new Error("404"), { status: 404 }),
    );

    render(<StudyScreen />);
    await userEvent.click(screen.getByText("pick-subject"));

    await waitFor(() => expect(screen.getByTestId("quiz-empty")).toBeInTheDocument());
    expect(screen.queryByTestId("study-status-banner")).not.toBeInTheDocument();
    expect(screen.queryByTestId("study-status-failed")).not.toBeInTheDocument();
  });
});
