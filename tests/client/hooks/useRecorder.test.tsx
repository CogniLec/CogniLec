import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useRecorder } from "../../../src/client/src/hooks/useRecorder";
import { _resetDbForTests } from "../../../src/client/src/services/db";
import { isRecordingActive } from "../../../src/client/src/services/recordingActivity";

vi.mock("../../../src/client/src/services/api", () => ({
  createSession: vi.fn().mockResolvedValue({ id: "server-session-1", subject_id: "subj-1", status: "created" }),
  uploadSessionChunk: vi.fn().mockResolvedValue(undefined),
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
    // Regression: the session id must come from the server (createSession),
    // not a client-only crypto.randomUUID() -- otherwise every chunk
    // upload 404s against a session that never existed server-side, and
    // nothing captured ever actually reaches the backend. See useRecorder.ts.
    expect(result.current.session?.id).toBe("server-session-1");
  });

  it("surfaces an error and does not start recording if session creation fails", async () => {
    const api = await import("../../../src/client/src/services/api");
    vi.mocked(api.createSession).mockRejectedValueOnce(new Error("network down"));

    const { result } = renderHook(() => useRecorder());

    act(() => {
      result.current.acknowledgeConsent();
    });

    await act(async () => {
      await result.current.startRecording("subj-1", "Physics");
    });

    expect(result.current.appState).not.toBe("RECORDING");
    expect(result.current.error).toMatch(/session/i);
  });
});

describe("useRecorder beforeunload guard (docs/gaps.md #33i)", () => {
  beforeEach(() => {
    _resetDbForTests();
  });

  it("warns on tab close while recording, and stops warning after stop", async () => {
    const { result } = renderHook(() => useRecorder());
    const addSpy = vi.spyOn(window, "addEventListener");
    const removeSpy = vi.spyOn(window, "removeEventListener");

    act(() => {
      result.current.acknowledgeConsent();
    });
    await act(async () => {
      await result.current.startRecording("subj-1", "Physics");
    });
    await waitFor(() => expect(result.current.appState).toBe("RECORDING"));

    expect(addSpy).toHaveBeenCalledWith("beforeunload", expect.any(Function));
    const handler = addSpy.mock.calls.find(([event]) => event === "beforeunload")?.[1] as
      | ((e: Event) => void)
      | undefined;
    expect(handler).toBeDefined();
    const fakeEvent = { preventDefault: vi.fn(), returnValue: "" } as unknown as BeforeUnloadEvent;
    handler?.(fakeEvent);
    expect(fakeEvent.preventDefault).toHaveBeenCalled();

    act(() => {
      result.current.stopRecording();
    });
    await waitFor(() => expect(result.current.appState).toBe("STOPPED"));
    expect(removeSpy).toHaveBeenCalledWith("beforeunload", handler);

    addSpy.mockRestore();
    removeSpy.mockRestore();
  });
});

describe("useRecorder recordingActivity wiring (docs/gaps.md #33j)", () => {
  beforeEach(() => {
    _resetDbForTests();
  });

  it("marks recording active while RECORDING and inactive once stopped", async () => {
    const { result } = renderHook(() => useRecorder());

    act(() => {
      result.current.acknowledgeConsent();
    });
    await act(async () => {
      await result.current.startRecording("subj-1", "Physics");
    });
    await waitFor(() => expect(result.current.appState).toBe("RECORDING"));
    expect(isRecordingActive()).toBe(true);

    act(() => {
      result.current.stopRecording();
    });
    await waitFor(() => expect(result.current.appState).toBe("STOPPED"));
    expect(isRecordingActive()).toBe(false);
  });
});
