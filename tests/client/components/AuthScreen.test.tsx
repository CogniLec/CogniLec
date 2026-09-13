import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AuthScreen } from "../../../src/client/src/components/AuthScreen";

describe("AuthScreen (S12 login/register UI)", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("calls onLogin with the entered credentials in login mode", async () => {
    const onLogin = vi.fn().mockResolvedValue(undefined);
    render(<AuthScreen onLogin={onLogin} />);

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/email/i), "user@example.com");
    await user.type(screen.getByLabelText(/password/i), "password123");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(onLogin).toHaveBeenCalledWith("user@example.com", "password123");
  });

  it("registers before logging in when switched to register mode", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "u1", email: "new@example.com", is_active: true }),
    }) as unknown as typeof fetch;
    const onLogin = vi.fn().mockResolvedValue(undefined);
    render(<AuthScreen onLogin={onLogin} />);

    const user = userEvent.setup();
    await user.click(screen.getByText(/need an account/i));
    await user.type(screen.getByLabelText(/email/i), "new@example.com");
    await user.type(screen.getByLabelText(/password/i), "password123");
    await user.click(screen.getByRole("button", { name: /register/i }));

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/auth/register"),
      expect.objectContaining({ method: "POST" }),
    );
    expect(onLogin).toHaveBeenCalledWith("new@example.com", "password123");
  });

  it("shows an error message when login fails", async () => {
    const onLogin = vi.fn().mockRejectedValue(new Error("Incorrect email or password"));
    render(<AuthScreen onLogin={onLogin} />);

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/email/i), "user@example.com");
    await user.type(screen.getByLabelText(/password/i), "wrongpassword");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password");
  });
});
