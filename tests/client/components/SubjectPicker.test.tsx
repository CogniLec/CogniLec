import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SubjectPicker } from "../../../src/client/src/components/SubjectPicker";

describe("SubjectPicker (T15.5 subject required)", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("renders the subject list from the mocked API and reports selection", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [
          { id: "s1", name: "Operating Systems", description: "CS 301" },
          { id: "s2", name: "Databases", description: "CS 302" },
        ],
        total: 2,
      }),
    }) as unknown as typeof fetch;

    const onSelect = vi.fn();
    render(<SubjectPicker selectedSubjectId={null} onSelect={onSelect} />);

    await waitFor(() => expect(screen.getByTestId("subject-picker")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText(/subject/i), "s2");
    expect(onSelect).toHaveBeenCalledWith({ id: "s2", name: "Databases", description: "CS 302" });
  });

  it("shows an empty state when no subjects are returned", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0 }),
    }) as unknown as typeof fetch;

    render(<SubjectPicker selectedSubjectId={null} onSelect={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId("subject-picker-empty")).toBeInTheDocument());
  });
});
