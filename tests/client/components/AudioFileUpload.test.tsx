import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AudioFileUpload } from "../../../src/client/src/components/AudioFileUpload";
import { installFakeXhr } from "../testUtils/fakeXhr";

describe("AudioFileUpload (docs/gaps.md #33i/#33j — MP4 support + upload progress)", () => {
  const originalFetch = globalThis.fetch;
  let restoreXhr: (() => void) | null = null;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    restoreXhr?.();
    restoreXhr = null;
  });

  it("creates a session, uploads the file, and reports the result", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "sess-1", subject_id: "subj-1", status: "created" }),
    }) as unknown as typeof fetch;

    const { calls, restore } = installFakeXhr([
      {
        status: 200,
        body: {
          session_id: "sess-1",
          filename: "lecture.mp4",
          total_chunks: 4,
          status: "processing",
          message: "Audio file queued for processing",
        },
      },
    ]);
    restoreXhr = restore;

    const onUploaded = vi.fn();
    render(<AudioFileUpload subjectId="subj-1" onUploaded={onUploaded} />);

    const user = userEvent.setup();
    const file = new File([new Uint8Array(1024)], "lecture.mp4", { type: "video/mp4" });
    await user.upload(screen.getByLabelText(/choose audio file/i), file);
    await user.click(screen.getByRole("button", { name: /upload/i }));

    await waitFor(() =>
      expect(screen.getByText(/queued for processing/i)).toBeInTheDocument(),
    );
    expect(calls[0].url).toContain("/sessions/sess-1/audio-file");
    expect(onUploaded).toHaveBeenCalledWith("Audio file queued for processing", "sess-1");

    // Regression: onUploaded already switches tabs automatically, but a
    // manual fallback must stay visible and available too, in case that
    // automatic switch doesn't fire in some environment/browser state.
    onUploaded.mockClear();
    await user.click(screen.getByRole("button", { name: /go to review/i }));
    expect(onUploaded).toHaveBeenCalledWith("Audio file queued for processing", "sess-1");
  });

  it("shows a friendly error on failure", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "sess-2", subject_id: "subj-1", status: "created" }),
    }) as unknown as typeof fetch;

    const { restore } = installFakeXhr([{ status: 500, statusText: "Internal Server Error" }]);
    restoreXhr = restore;

    render(<AudioFileUpload subjectId="subj-1" />);

    const user = userEvent.setup();
    const file = new File([new Uint8Array(1024)], "lecture.mp3", { type: "audio/mpeg" });
    await user.upload(screen.getByLabelText(/choose audio file/i), file);
    await user.click(screen.getByRole("button", { name: /upload/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/went wrong/i));
  });
});
