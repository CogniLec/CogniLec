import { describe, it, expect, vi } from "vitest";
import {
  isRecordingActive,
  setRecordingActive,
  onceRecordingStops,
} from "../../../src/client/src/services/recordingActivity";

describe("recordingActivity (docs/gaps.md #33j)", () => {
  it("tracks active state and fires stop listeners exactly once", () => {
    setRecordingActive(true);
    expect(isRecordingActive()).toBe(true);

    const listener = vi.fn();
    onceRecordingStops(listener);
    expect(listener).not.toHaveBeenCalled();

    setRecordingActive(false);
    expect(isRecordingActive()).toBe(false);
    expect(listener).toHaveBeenCalledTimes(1);

    // A second stop (already inactive) must not re-fire the same listener.
    setRecordingActive(false);
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
