import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { fetchSubjects, createSession, uploadMaterial } from "../../../src/client/src/services/api";
import { login, getAccessToken, setSessionExpiredHandler } from "../../../src/client/src/services/auth";
import { installFakeXhr } from "../testUtils/fakeXhr";

describe("api service (mocked HTTP layer)", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("maps the subjects list response into Subject[]", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [{ id: "s1", name: "Operating Systems", description: "CS 301" }],
        total: 1,
      }),
    }) as unknown as typeof fetch;

    const subjects = await fetchSubjects();
    expect(subjects).toEqual([{ id: "s1", name: "Operating Systems", description: "CS 301" }]);
  });

  it("throws on a non-ok response", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
    }) as unknown as typeof fetch;

    await expect(fetchSubjects()).rejects.toThrow(/500/);
  });

  it("posts a session create request with the expected body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "sess-1", subject_id: "s1", status: "created" }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const result = await createSession("s1", "content");
    expect(result.id).toBe("sess-1");
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/sessions/"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ subject_id: "s1", session_type: "content" }),
      }),
    );
  });
});

describe("api service — 401 refresh-and-retry (docs/gaps.md #33h)", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    localStorage.clear();
  });

  it("refreshes the token once on a 401 and retries the original request", async () => {
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        access_token: "old-token",
        refresh_token: "old-refresh",
        token_type: "bearer",
      }),
    }) as unknown as typeof fetch;
    await login("a@b.com", "pw");

    const fetchMock = vi
      .fn()
      // 1: the original request, rejected as expired
      .mockResolvedValueOnce({ ok: false, status: 401, statusText: "Unauthorized" })
      // 2: the refresh call
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          access_token: "new-token",
          refresh_token: "new-refresh",
          token_type: "bearer",
        }),
      })
      // 3: the retried original request, now succeeding
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ items: [{ id: "s1", name: "Subj", description: null }], total: 1 }),
      });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const subjects = await fetchSubjects();

    expect(subjects).toEqual([{ id: "s1", name: "Subj", description: null }]);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const retryCall = fetchMock.mock.calls[2];
    expect((retryCall[1] as RequestInit).headers).toMatchObject({
      Authorization: "Bearer new-token",
    });
    expect(getAccessToken()).toBe("new-token");
  });

  it("clears tokens and notifies session expiry when the refresh itself fails", async () => {
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        access_token: "old-token",
        refresh_token: "old-refresh",
        token_type: "bearer",
      }),
    }) as unknown as typeof fetch;
    await login("a@b.com", "pw");

    const expiredHandler = vi.fn();
    setSessionExpiredHandler(expiredHandler);

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 401, statusText: "Unauthorized" })
      .mockResolvedValueOnce({ ok: false, status: 401, statusText: "Unauthorized" });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await expect(fetchSubjects()).rejects.toThrow(/401/);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(expiredHandler).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBeNull();

    setSessionExpiredHandler(() => {});
  });
});

describe("xhrUpload — refresh-and-retry on 401 (docs/gaps.md #33j)", () => {
  const originalFetch = globalThis.fetch;
  let restoreXhr: (() => void) | null = null;

  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    restoreXhr?.();
    restoreXhr = null;
    localStorage.clear();
  });

  it("refreshes the token once on a 401 and retries the upload", async () => {
    globalThis.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        access_token: "old-token",
        refresh_token: "old-refresh",
        token_type: "bearer",
      }),
    }) as unknown as typeof fetch;
    await login("a@b.com", "pw");

    // The refresh call itself still goes through fetch (auth.ts), while
    // the upload goes through the fake XHR.
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: "new-token",
        refresh_token: "new-refresh",
        token_type: "bearer",
      }),
    }) as unknown as typeof fetch;

    const { calls, restore } = installFakeXhr([
      { status: 401 },
      { status: 200, body: { upload_id: "u1", status: "completed", items_extracted: 1, message: "ok", error_details: null } },
    ]);
    restoreXhr = restore;

    const file = new File(["x"], "notes.md", { type: "text/markdown" });
    const result = await uploadMaterial("subj-1", file);

    expect(result.upload_id).toBe("u1");
    expect(calls).toHaveLength(2);
    expect(calls[1].headers.Authorization).toBe("Bearer new-token");
  });
});
