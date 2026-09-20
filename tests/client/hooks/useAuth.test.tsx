import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useAuth } from "../../../src/client/src/hooks/useAuth";

describe("useAuth session-check failure handling (docs/gaps.md #33j)", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("lis_access_token", "existing-token");
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    localStorage.clear();
  });

  it("logs the user out on a genuine 401", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
    }) as unknown as typeof fetch;

    const { result } = renderHook(() => useAuth());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.user).toBeNull();
    expect(result.current.checkFailed).toBe(false);
  });

  it("does not log the user out on a network/5xx blip, and offers a retry", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
    }) as unknown as typeof fetch;

    const { result } = renderHook(() => useAuth());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.checkFailed).toBe(true);
    expect(result.current.user).toBeNull();

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "u1", email: "a@b.com", is_active: true }),
    }) as unknown as typeof fetch;

    act(() => {
      result.current.retryCheck();
    });

    await waitFor(() => expect(result.current.checkFailed).toBe(false));
    expect(result.current.user?.email).toBe("a@b.com");
  });
});
