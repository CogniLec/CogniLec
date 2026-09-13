import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchSubjects, createSession } from "../../../src/client/src/services/api";

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
