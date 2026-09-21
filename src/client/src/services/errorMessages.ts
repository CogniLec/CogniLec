import { CONFIG } from "../config";
import { ApiError } from "./api";

/**
 * Maps a caught error to human-readable copy instead of the raw
 * "API request failed: 409 Conflict" / "413 Request Entity Too Large"
 * text that used to reach the user verbatim (docs/gaps.md #33j).
 * `overrides` lets a specific call site supply context-appropriate copy
 * for a status (e.g. "That subject name is already in use." for a 409 on
 * subject creation) without duplicating the whole switch.
 */
export function friendlyErrorMessage(
  err: unknown,
  overrides?: Partial<Record<number, string>>,
): string {
  if (err instanceof ApiError) {
    const override = overrides?.[err.status];
    if (override) return override;
    switch (err.status) {
      case 401:
        return "Your session isn't valid anymore — please log in again.";
      case 409:
        return "That already exists — try a different name.";
      case 413:
        return "That file is too large. The limit is 20MB.";
      case 500:
      case 502:
      case 503:
        return "Something went wrong on our end. Please try again.";
      default:
        return err.message;
    }
  }
  if (err instanceof TypeError && /fetch|network/i.test(err.message)) {
    // A network-level failure (never reached the server). Name the address
    // that was tried so "Failed to fetch" is diagnosable without DevTools.
    return `Couldn't reach the server at ${CONFIG.apiBaseUrl}. Check your connection, or reload to pick up a new server address.`;
  }
  return err instanceof Error ? err.message : "Something went wrong.";
}
