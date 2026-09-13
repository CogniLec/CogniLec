import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useRecorder } from "../../../src/client/src/hooks/useRecorder";
import { _resetDbForTests } from "../../../src/client/src/services/db";

vi.mock("../../../src/client/src/services/api", () => ({
  fetchPresignedUploadUrl: vi.fn().mockResolvedValue("https://upload.example/chunk"),
  uploadChunkToPresignedUrl: vi.fn().mockResolvedValue(undefined),
}));

describe("useRecorder gating (T15.4 consent, T15.5 subject)", () => {
  beforeEach(() => {
    _resetDbForTests();
  });

  it("refuses to start without a subject id", async () => {
    const { result } = renderHook(() => useRecorder());

    await act(async () => {
      await result.current.startRecording("", "");
    });

    expect(result.current.appState).not.toBe("RECORDING");
    expect(result.current.error).toMatch(/subject/i);
  });

  it("refuses to start without consent acknowledgement, and shows CONSENT_REQUIRED", async () => {
    const { result } = renderHook(() => useRecorder());

    await act(async () => {
      await result.current.startRecording("subj-1", "Physics");
    });

    await waitFor(() => {
      expect(result.current.appState).toBe("CONSENT_REQUIRED");
    });
  });

  it("starts recording once both subject and consent are present", async () => {
    const { result } = renderHook(() => useRecorder());

    act(() => {
      result.current.acknowledgeConsent();
    });

    await act(async () => {
      await result.current.startRecording("subj-1", "Physics");
    });

    await waitFor(() => {
      expect(result.current.appState).toBe("RECORDING");
    });
    expect(result.current.session?.subjectId).toBe("subj-1");
  });
});
