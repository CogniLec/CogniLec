import { describe, it, expect } from "vitest";
import { friendlyErrorMessage } from "../../../src/client/src/services/errorMessages";
import { ApiError } from "../../../src/client/src/services/api";

describe("friendlyErrorMessage (docs/gaps.md #33j)", () => {
  it("maps known statuses to human copy", () => {
    expect(friendlyErrorMessage(new ApiError(409, "Conflict"))).toMatch(/already exists/i);
    expect(friendlyErrorMessage(new ApiError(413, "Payload Too Large"))).toMatch(/too large/i);
    expect(friendlyErrorMessage(new ApiError(401, "Unauthorized"))).toMatch(/log in/i);
    expect(friendlyErrorMessage(new ApiError(500, "Internal Server Error"))).toMatch(
      /went wrong/i,
    );
  });

  it("lets a call site override the copy for a specific status", () => {
    expect(
      friendlyErrorMessage(new ApiError(409, "Conflict"), {
        409: "A subject with that name already exists.",
      }),
    ).toBe("A subject with that name already exists.");
  });

  it("falls back to the raw message for an unmapped status", () => {
    expect(friendlyErrorMessage(new ApiError(418, "I'm a teapot"))).toContain("418");
  });

  it("falls back to a generic message for a non-Error value", () => {
    expect(friendlyErrorMessage("boom")).toBe("Something went wrong.");
  });
});
