import { CONFIG } from "../config";
import type { AuthUser } from "../types";

// S12 auth (fastapi-users-style JWT, src/api/routes/auth.py): register,
// login, and the current user. Kept separate from api.ts's `request()` to
// avoid a circular import (api.ts reads the stored token from here).

const TOKEN_STORAGE_KEY = "lis_access_token";
const REFRESH_TOKEN_STORAGE_KEY = "lis_refresh_token";

export function getAccessToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function setAccessToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    // localStorage unavailable (private browsing, etc.) — session simply
    // won't persist across reloads.
  }
}

export function getRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function setRefreshToken(token: string): void {
  try {
    localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, token);
  } catch {
    // no-op, same as setAccessToken above
  }
}

export function clearAccessToken(): void {
  try {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
  } catch {
    // no-op
  }
}

// Lets api.ts tell the rest of the app "the user's session is gone, show
// the login screen" without a circular import — set once by useAuth.ts.
let sessionExpiredHandler: (() => void) | null = null;

export function setSessionExpiredHandler(handler: () => void): void {
  sessionExpiredHandler = handler;
}

function notifySessionExpired(): void {
  clearAccessToken();
  sessionExpiredHandler?.();
}

/**
 * Exchanges the stored refresh token for a new access/refresh pair.
 * Previously the refresh_token returned by /login was fetched and
 * immediately discarded (docs/gaps.md #33h) -- api.ts's `request()` had no
 * 401 handling at all, so an expired access token surfaced as a raw
 * "API request failed: 401 Unauthorized" anywhere in the app instead of
 * transparently re-authenticating. Returns the new access token on
 * success; on failure, clears both tokens and notifies the app so it can
 * fall back to the login screen.
 */
export async function refreshAccessToken(): Promise<string> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    notifySessionExpired();
    throw new Error("No refresh token available");
  }
  const res = await fetch(`${CONFIG.apiBaseUrl}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) {
    notifySessionExpired();
    throw new Error("Session expired");
  }
  const tokens = (await res.json()) as TokenResponse;
  setAccessToken(tokens.access_token);
  setRefreshToken(tokens.refresh_token);
  return tokens.access_token;
}

interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

async function authRequest<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(`${CONFIG.apiBaseUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    const message =
      (detail && typeof detail === "object" && "detail" in detail && String(detail.detail)) ||
      `${res.status} ${res.statusText}`;
    throw new Error(message);
  }
  return (await res.json()) as T;
}

export async function register(email: string, password: string): Promise<AuthUser> {
  return authRequest<AuthUser>("/api/v1/auth/register", { email, password });
}

export async function login(email: string, password: string): Promise<void> {
  const tokens = await authRequest<TokenResponse>("/api/v1/auth/login", { email, password });
  setAccessToken(tokens.access_token);
  setRefreshToken(tokens.refresh_token);
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  const res = await fetch(`${CONFIG.apiBaseUrl}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${getAccessToken() ?? ""}` },
  });
  if (!res.ok) {
    throw new Error(`Failed to load current user: ${res.status}`);
  }
  return (await res.json()) as AuthUser;
}

export function logout(): void {
  clearAccessToken();
}
