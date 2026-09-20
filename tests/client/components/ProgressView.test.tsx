import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ProgressView } from "../../../src/client/src/components/ProgressView";

describe("ProgressView (docs/gaps.md #33j — retry on fetch failure)", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("renders progress stats on success", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        subject_id: "subj-1",
        total_reviews: 10,
        correct_reviews: 7,
        accuracy: 0.7,
        recent_outcomes: [],
      }),
    }) as unknown as typeof fetch;

    render(<ProgressView subjectId="subj-1" />);
    await waitFor(() => expect(screen.getByTestId("progress-view")).toBeInTheDocument());
    expect(screen.getByText("70%")).toBeInTheDocument();
  });

  it("shows a Retry button on failure, which re-fetches", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 500, statusText: "Internal Server Error" })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          subject_id: "subj-1",
          total_reviews: 0,
          correct_reviews: 0,
          accuracy: 0,
          recent_outcomes: [],
        }),
      });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<ProgressView subjectId="subj-1" />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(screen.getByTestId("progress-view")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shows placeholder copy instead of an empty panel when there's no activity yet (docs/gaps.md #33j)", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        subject_id: "subj-1",
        total_reviews: 0,
        correct_reviews: 0,
        accuracy: 0,
        recent_outcomes: [],
      }),
    }) as unknown as typeof fetch;

    render(<ProgressView subjectId="subj-1" />);
    await waitFor(() => expect(screen.getByTestId("progress-no-activity")).toBeInTheDocument());
  });
});
