import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConsentGate } from "../../../src/client/src/components/ConsentGate";

describe("ConsentGate (T15.4 consent gate)", () => {
  it("disables acknowledge until the checkbox is checked, then calls onAcknowledge", async () => {
    const user = userEvent.setup();
    const onAcknowledge = vi.fn();
    render(<ConsentGate onAcknowledge={onAcknowledge} />);

    const button = screen.getByRole("button", { name: /acknowledge consent/i });
    expect(button).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /i consent to being recorded/i }));
    expect(button).toBeEnabled();

    await user.click(button);
    expect(onAcknowledge).toHaveBeenCalledTimes(1);
  });
});
