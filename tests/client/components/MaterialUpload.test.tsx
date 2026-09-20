import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MaterialUpload } from "../../../src/client/src/components/MaterialUpload";

describe("MaterialUpload (S51 syllabus/reference material upload)", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("uploads a chosen file and shows the extraction result", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        upload_id: "up-1",
        status: "completed",
        items_extracted: 12,
        message: "Parsed successfully",
        error_details: null,
      }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<MaterialUpload subjectId="subj-1" />);

    const user = userEvent.setup();
    const file = new File(["%PDF-1.4 fake"], "syllabus.pdf", { type: "application/pdf" });
    const input = screen.getByLabelText(/choose file/i);
    await user.upload(input, file);

    await user.click(screen.getByRole("button", { name: /upload/i }));

    await waitFor(() =>
      expect(screen.getByText(/Parsed successfully \(12 items extracted\)/)).toBeInTheDocument(),
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/subjects/subj-1/syllabus");
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("shows an error message when the upload fails", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 413,
      statusText: "Payload Too Large",
    }) as unknown as typeof fetch;

    render(<MaterialUpload subjectId="subj-1" />);

    const user = userEvent.setup();
    const file = new File(["x"], "notes.md", { type: "text/markdown" });
    await user.upload(screen.getByLabelText(/choose file/i), file);
    await user.click(screen.getByRole("button", { name: /upload/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/413/));
  });

  it("shows a warning (not success) styling when 0 items were extracted (docs/gaps.md #33i)", async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        upload_id: "up-2",
        status: "completed",
        items_extracted: 0,
        message: "Parsed successfully",
        error_details: null,
      }),
    }) as unknown as typeof fetch;

    render(<MaterialUpload subjectId="subj-1" />);

    const user = userEvent.setup();
    const file = new File(["scan"], "scanned.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText(/choose file/i), file);
    await user.click(screen.getByRole("button", { name: /upload/i }));

    const result = await screen.findByTestId("material-upload-result");
    expect(result).toHaveAttribute("data-variant", "warning");
    expect(result).toHaveTextContent(/no content could be extracted/i);
  });
});
