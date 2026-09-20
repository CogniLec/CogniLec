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

  it("shows a Retry button on a load failure, which re-fetches (docs/gaps.md #33j)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 500, statusText: "Internal Server Error" })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ items: [{ id: "s1", name: "Subj", description: null }], total: 1 }),
      });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<SubjectPicker selectedSubjectId={null} onSelect={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(screen.getByTestId("subject-picker")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shows friendly copy (not raw HTTP text) for a duplicate subject name, with no Retry button", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [], total: 0 }) })
      .mockResolvedValueOnce({ ok: false, status: 409, statusText: "Conflict" }) as unknown as typeof fetch;

    render(<SubjectPicker selectedSubjectId={null} onSelect={vi.fn()} />);
    await waitFor(() => expect(screen.getByTestId("subject-picker-empty")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/new name/i), "Duplicate");
    await user.click(screen.getByRole("button", { name: /create subject/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/already exists/i),
    );
    expect(screen.queryByRole("button", { name: /^retry$/i })).not.toBeInTheDocument();
  });
});
