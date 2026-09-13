import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import {
  login,
  register,
  fetchCurrentUser,
  logout,
  getAccessToken,
} from "../../../src/client/src/services/auth";

describe("auth service (S12 login/register/me)", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("stores the access token returned by login", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: "abc123",
        refresh_token: "def456",
        token_type: "bearer",
      }),
    }) as unknown as typeof fetch;

    await login("user@example.com", "password123");
    expect(getAccessToken()).toBe("abc123");
  });

  it("throws the server-provided detail message on a failed login", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      statusText: "Unauthorized",
      json: async () => ({ detail: "Incorrect email or password" }),
    }) as unknown as typeof fetch;

    await expect(login("user@example.com", "wrong")).rejects.toThrow(
      "Incorrect email or password",
    );
  });

  it("posts registration fields and returns the created user", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "u1", email: "user@example.com", is_active: true }),
    }) as unknown as typeof fetch;

    const user = await register("user@example.com", "password123");
    expect(user).toEqual({ id: "u1", email: "user@example.com", is_active: true });
  });

  it("fetches the current user with the stored bearer token", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ access_token: "tok", refresh_token: "r", token_type: "bearer" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: "u1", email: "user@example.com", is_active: true }),
      }) as unknown as typeof fetch;

    await login("user@example.com", "password123");
    const user = await fetchCurrentUser();
    expect(user.email).toBe("user@example.com");

    const authHeader = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[1][1].headers
      .Authorization;
    expect(authHeader).toBe("Bearer tok");
  });

  it("clears the stored token on logout", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ access_token: "tok", refresh_token: "r", token_type: "bearer" }),
    }) as unknown as typeof fetch;
    await login("user@example.com", "password123");
    expect(getAccessToken()).toBe("tok");

    logout();
    expect(getAccessToken()).toBeNull();
  });
});
