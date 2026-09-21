import { describe, it, expect, vi, afterEach } from "vitest";
import { CONFIG, loadRuntimeConfig } from "../../../src/client/src/config";

describe("loadRuntimeConfig", () => {
  const original = globalThis.fetch;
  const buildTime = CONFIG.apiBaseUrl;
  afterEach(() => {
    globalThis.fetch = original;
    CONFIG.apiBaseUrl = buildTime;
  });

  it("overrides the build-time URL from config.json (trailing slash trimmed)", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ apiBaseUrl: "https://new.example.com/" }),
    }) as unknown as typeof fetch;
    await loadRuntimeConfig();
    expect(CONFIG.apiBaseUrl).toBe("https://new.example.com");
  });

  it("keeps the build-time URL when config.json is empty, missing or unreachable", async () => {
    for (const impl of [
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ apiBaseUrl: "" }) }),
      vi.fn().mockResolvedValue({ ok: false }),
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    ]) {
      globalThis.fetch = impl as unknown as typeof fetch;
      await loadRuntimeConfig();
      expect(CONFIG.apiBaseUrl).toBe(buildTime);
    }
  });
});
