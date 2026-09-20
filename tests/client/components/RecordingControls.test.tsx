import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RecordingControls } from "../../../src/client/src/components/RecordingControls";

describe("RecordingControls", () => {
  it("shows the formatted elapsed timer and chunk count", () => {
    render(
      <RecordingControls
        isRecording
        canStart={false}
        elapsedMs={3_661_000} // 1h 1m 1s
        chunkCount={42}
        onStart={vi.fn()}
        onStop={vi.fn()}
      />,
    );
    expect(screen.getByTestId("elapsed-timer")).toHaveTextContent("01:01:01");
    expect(screen.getByTestId("chunk-count")).toHaveTextContent("42");
  });

  it("disables Start Recording when canStart is false (T15.4/T15.5 gating)", () => {
    render(
      <RecordingControls
        isRecording={false}
        canStart={false}
        elapsedMs={0}
        chunkCount={0}
        onStart={vi.fn()}
        onStop={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /start recording/i })).toBeDisabled();
  });

  it("invokes onStart when enabled and clicked", async () => {
    const user = userEvent.setup();
    const onStart = vi.fn();
    render(
      <RecordingControls
        isRecording={false}
        canStart
        elapsedMs={0}
        chunkCount={0}
        onStart={onStart}
        onStop={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: /start recording/i }));
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it("shows Stop Recording while recording and invokes onStop", async () => {
    const user = userEvent.setup();
    const onStop = vi.fn();
    render(
      <RecordingControls
        isRecording
        canStart={false}
        elapsedMs={0}
        chunkCount={1}
        onStart={vi.fn()}
        onStop={onStop}
      />,
    );
    await user.click(screen.getByRole("button", { name: /stop recording/i }));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it("shows syncing/failed upload counts and wires the retry button (docs/gaps.md #33i)", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <RecordingControls
        isRecording
        canStart={false}
        elapsedMs={0}
        chunkCount={5}
        onStart={vi.fn()}
        onStop={vi.fn()}
        syncingCount={2}
        failedUploadCount={1}
        onRetryFailedUploads={onRetry}
      />,
    );
    const status = screen.getByTestId("upload-sync-status");
    expect(status).toHaveTextContent("2 syncing");
    expect(status).toHaveTextContent("1 failed to sync");
    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("shows no upload-sync status when nothing is syncing or failed", () => {
    render(
      <RecordingControls
        isRecording={false}
        canStart={false}
        elapsedMs={0}
        chunkCount={0}
        onStart={vi.fn()}
        onStop={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("upload-sync-status")).not.toBeInTheDocument();
  });
});
