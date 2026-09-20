import { useCallback, useEffect, useState } from "react";
import {
  fetchCurrentUser,
  getAccessToken,
  login as loginRequest,
  logout as logoutRequest,
  setSessionExpiredHandler,
} from "../services/auth";
import type { AuthUser } from "../types";

export interface UseAuthResult {
  user: AuthUser | null;
  loading: boolean;
  error: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

export function useAuth(): UseAuthResult {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getAccessToken()) {
      setLoading(false);
      return;
    }
    fetchCurrentUser()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  // Wired to api.ts's authorizedFetch: fires when a 401 survives a refresh
  // attempt (expired/invalid refresh token), so the user is dropped to the
  // login screen with an explanation instead of every subsequent API call
  // separately throwing a raw "API request failed: 401" (docs/gaps.md #33h).
  useEffect(() => {
    setSessionExpiredHandler(() => {
      setUser(null);
      setError("Your session expired — please log in again.");
    });
    return () => setSessionExpiredHandler(() => {});
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    setError(null);
    try {
      await loginRequest(email, password);
      const me = await fetchCurrentUser();
      setUser(me);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
      throw err;
    }
  }, []);

  const logout = useCallback(() => {
    logoutRequest();
    setUser(null);
  }, []);

  return { user, loading, error, login, logout };
}
