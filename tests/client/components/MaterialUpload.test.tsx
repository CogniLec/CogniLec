import { describe, it, expect, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MaterialUpload } from "../../../src/client/src/components/MaterialUpload";
import { installFakeXhr } from "../testUtils/fakeXhr";

describe("MaterialUpload (S51 syllabus/reference material upload)", () => {
  let restoreXhr: (() => void) | null = null;

  afterEach(() => {
    restoreXhr?.();
    restoreXhr = null;
  });

  it("uploads a chosen file and shows the extraction result", async () => {
    const { calls, restore } = installFakeXhr([
      {
        status: 200,
        body: {
          upload_id: "up-1",
          status: "completed",
          items_extracted: 12,
          message: "Parsed successfully",
          error_details: null,
        },
      },
    ]);
    restoreXhr = restore;

    render(<MaterialUpload subjectId="subj-1" />);

    const user = userEvent.setup();
    const file = new File(["%PDF-1.4 fake"], "syllabus.pdf", { type: "application/pdf" });
    const input = screen.getByLabelText(/choose file/i);
    await user.upload(input, file);

    await user.click(screen.getByRole("button", { name: /upload/i }));

    await waitFor(() =>
      expect(screen.getByText(/Parsed successfully \(12 items extracted\)/)).toBeInTheDocument(),
    );

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toContain("/subjects/subj-1/syllabus");
  });

  it("rejects an oversize file before ever uploading (docs/gaps.md #33j)", async () => {
    const { calls, restore } = installFakeXhr([{ status: 200, body: {} }]);
    restoreXhr = restore;

    render(<MaterialUpload subjectId="subj-1" />);

    const user = userEvent.setup();
    const oversized = new File([new Uint8Array(21 * 1024 * 1024)], "huge.pdf", {
      type: "application/pdf",
    });
    await user.upload(screen.getByLabelText(/choose file/i), oversized);
    await user.click(screen.getByRole("button", { name: /upload/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/too large/i));
    expect(calls).toHaveLength(0);
  });

  it("shows an error message when the upload fails", async () => {
    const { restore } = installFakeXhr([{ status: 413, statusText: "Payload Too Large" }]);
    restoreXhr = restore;

    render(<MaterialUpload subjectId="subj-1" />);

    const user = userEvent.setup();
    const file = new File(["x"], "notes.md", { type: "text/markdown" });
    await user.upload(screen.getByLabelText(/choose file/i), file);
    await user.click(screen.getByRole("button", { name: /upload/i }));

    // Friendly copy, not the raw "413 Request Entity Too Large" (docs/gaps.md #33j).
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/too large/i));
  });

  it("shows a warning (not success) styling when 0 items were extracted (docs/gaps.md #33i)", async () => {
    const { restore } = installFakeXhr([
      {
        status: 200,
        body: {
          upload_id: "up-2",
          status: "completed",
          items_extracted: 0,
          message: "Parsed successfully",
          error_details: null,
        },
      },
    ]);
    restoreXhr = restore;

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
