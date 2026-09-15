import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QuizCard } from "../../../src/client/src/components/QuizCard";

describe("QuizCard (manual-review-app quiz/recall loop)", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("shows the front, then reveals the real note and lets the user rate recall", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          id: "card-1",
          subject_id: "subj-1",
          topic_label: "Photosynthesis",
          front: "What converts light to sugar?",
          back: "Chlorophyll in chloroplasts",
          due_at: "2026-01-01T00:00:00Z",
          last_review_at: null,
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          flashcard: {
            id: "card-1",
            subject_id: "subj-1",
            topic_label: "Photosynthesis",
            front: "What converts light to sugar?",
            back: "Chlorophyll in chloroplasts",
            due_at: "2026-01-08T00:00:00Z",
            last_review_at: "2026-01-01T00:00:00Z",
          },
          correction_recorded: false,
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          id: "card-2",
          subject_id: "subj-1",
          topic_label: "Photosynthesis",
          front: "Next card",
          back: "Next answer",
          due_at: "2026-01-01T00:00:00Z",
          last_review_at: null,
        }),
      });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<QuizCard subjectId="subj-1" />);

    await waitFor(() => expect(screen.getByTestId("quiz-card")).toBeInTheDocument());
    expect(screen.getByText("What converts light to sugar?")).toBeInTheDocument();
    expect(screen.queryByTestId("quiz-answer")).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByText("Reveal the actual note"));

    expect(screen.getByTestId("quiz-answer")).toHaveTextContent("Chlorophyll in chloroplasts");

    await user.click(screen.getByLabelText(/Yes, I knew it/));
    await user.click(screen.getByText("Good"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const reviewCall = fetchMock.mock.calls[1];
    expect(reviewCall[0]).toContain("/flashcards/card-1/review");
    expect(JSON.parse(reviewCall[1].body)).toEqual({
      rating: 3,
      self_correct: true,
      consent_for_training: true,
    });
  });

  it("shows an empty state when no flashcards exist yet", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: "Not Found",
    }) as unknown as typeof fetch;

    render(<QuizCard subjectId="subj-1" />);
    await waitFor(() => expect(screen.getByTestId("quiz-empty")).toBeInTheDocument());
    // Regression: a 404 here means "nothing due yet," a normal state for a
    // new subject -- it must show the friendly copy, not the raw
    // "API request failed: 404 Not Found" fetch error text.
    expect(screen.getByTestId("quiz-empty")).toHaveTextContent(
      "No flashcards available for this subject yet.",
    );
  });

  it("shows the real error message when the flashcard request genuinely fails", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
    }) as unknown as typeof fetch;

    render(<QuizCard subjectId="subj-1" />);
    await waitFor(() => expect(screen.getByTestId("quiz-empty")).toBeInTheDocument());
    expect(screen.getByTestId("quiz-empty")).toHaveTextContent("API request failed: 500");
  });
});
