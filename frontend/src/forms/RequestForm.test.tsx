import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import RequestForm from "./RequestForm";

// Mock the API client. The mock exports a real ApiError class so the component's
// `err instanceof ApiError` checks work against the errors we throw here.
vi.mock("../api/client", () => {
  class ApiError extends Error {
    code: string;
    retryable: boolean;
    status: number;
    constructor(code: string, message: string, retryable = false, status = 0) {
      super(message);
      this.name = "ApiError";
      this.code = code;
      this.retryable = retryable;
      this.status = status;
    }
  }
  return {
    ApiError,
    submitRequest: vi.fn(),
    newClientMessageId: vi.fn(() => "cmid_test"),
  };
});

import { ApiError, submitRequest } from "../api/client";

const mockSubmit = vi.mocked(submitRequest);

afterEach(() => {
  vi.clearAllMocks();
});

function renderStrategyForm(overrides: Partial<React.ComponentProps<typeof RequestForm>> = {}) {
  const onClose = vi.fn();
  const onSubmitted = vi.fn();
  render(
    <RequestForm
      type="strategy_call"
      conversationId="cnv_1"
      token="tok_1"
      onClose={onClose}
      onSubmitted={onSubmitted}
      {...overrides}
    />,
  );
  return { onClose, onSubmitted };
}

function fillStrategyFields() {
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Ada Smith" } });
  fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "ada@acme.com" } });
  fireEvent.change(screen.getByLabelText("Company"), { target: { value: "Acme" } });
  fireEvent.change(screen.getByLabelText(/what would you like to discuss/i), {
    target: { value: "Evaluate an AI roadmap" },
  });
}

describe("RequestForm review flow", () => {
  it("fills a strategy_call form, reviews with a masked email + consent, and submits", async () => {
    mockSubmit.mockResolvedValue({
      request_id: "req_1",
      status: "received",
      reference: "REQ-TEST",
    });
    const { onSubmitted } = renderStrategyForm();

    fillStrategyFields();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    // Review shows the masked email and the consent statement.
    expect(screen.getByText("a***@acme.com")).toBeInTheDocument();
    expect(screen.queryByText("ada@acme.com")).not.toBeInTheDocument();
    expect(screen.getByText(/By submitting this request/i)).toBeInTheDocument();

    // Confirm requires consent first.
    fireEvent.click(screen.getByLabelText(/i have read and agree/i));
    fireEvent.click(screen.getByRole("button", { name: /submit request/i }));

    await waitFor(() => expect(mockSubmit).toHaveBeenCalledTimes(1));
    expect(mockSubmit).toHaveBeenCalledWith(
      "tok_1",
      expect.objectContaining({
        type: "strategy_call",
        conversation_id: "cnv_1",
        confirmed: true,
        consent_version: "consent-2026-07",
        contact: { name: "Ada Smith", email: "ada@acme.com", company: "Acme" },
        fields: { reason: "Evaluate an AI roadmap" },
      }),
      "cmid_test",
    );

    // Success shows the reference and notifies the parent.
    expect(await screen.findByText(/Reference: REQ-TEST/)).toBeInTheDocument();
    expect(onSubmitted).toHaveBeenCalledWith("REQ-TEST");
  });
});

describe("RequestForm validation", () => {
  it("blocks advancing to review when the email is invalid", () => {
    renderStrategyForm();
    fillStrategyFields();
    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "not-an-email" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    // Still on the edit step (no consent statement yet) and an error is announced.
    expect(screen.queryByText(/By submitting this request/i)).not.toBeInTheDocument();
    expect(screen.getByText(/valid email address/i)).toBeInTheDocument();
    expect(mockSubmit).not.toHaveBeenCalled();
  });

  it("blocks advancing when a required field is missing", () => {
    renderStrategyForm();
    fillStrategyFields();
    fireEvent.change(screen.getByLabelText("Company"), { target: { value: "" } });

    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    expect(screen.queryByText(/By submitting this request/i)).not.toBeInTheDocument();
    expect(screen.getByText(/please enter your company/i)).toBeInTheDocument();
    expect(mockSubmit).not.toHaveBeenCalled();
  });

  it("requires consent before Confirm submits", () => {
    renderStrategyForm();
    fillStrategyFields();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));

    // Click Submit without checking consent.
    fireEvent.click(screen.getByRole("button", { name: /submit request/i }));

    expect(mockSubmit).not.toHaveBeenCalled();
    expect(screen.getByText(/please confirm consent/i)).toBeInTheDocument();
  });
});

describe("RequestForm failure handling", () => {
  it("preserves the draft when submit fails with a non-duplicate ApiError", async () => {
    mockSubmit.mockRejectedValue(new ApiError("INTERNAL_ERROR", "boom", false, 500));
    renderStrategyForm();

    fillStrategyFields();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    fireEvent.click(screen.getByLabelText(/i have read and agree/i));
    fireEvent.click(screen.getByRole("button", { name: /submit request/i }));

    // Failure banner appears; draft is not cleared.
    expect(await screen.findByText(/was not submitted/i)).toBeInTheDocument();

    // Return to review, then edit — the entered values are still there.
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(screen.getByText("a***@acme.com")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByLabelText("Work email")).toHaveValue("ada@acme.com");
    expect(screen.getByLabelText("Name")).toHaveValue("Ada Smith");
  });

  it("shows the duplicate notice on DUPLICATE_ACTION", async () => {
    const err = new ApiError("DUPLICATE_ACTION", "dup", false, 409);
    (err as unknown as { reference: string }).reference = "REQ-DUP";
    mockSubmit.mockRejectedValue(err);
    renderStrategyForm();

    fillStrategyFields();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    fireEvent.click(screen.getByLabelText(/i have read and agree/i));
    fireEvent.click(screen.getByRole("button", { name: /submit request/i }));

    expect(await screen.findByText(/already been submitted/i)).toBeInTheDocument();
    expect(screen.getByText(/REQ-DUP/)).toBeInTheDocument();
  });
});
