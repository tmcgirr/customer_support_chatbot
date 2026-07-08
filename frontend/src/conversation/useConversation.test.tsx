import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StreamEvent } from "../types";
import { ERROR_COPY } from "./copy";
import { ConversationView } from "./ConversationView";
import { useConversation } from "./useConversation";

// Mock the API client but keep the real ApiError class so `instanceof` checks work.
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    createConversation: vi.fn(),
    sendMessage: vi.fn(),
    submitFeedback: vi.fn(),
    newClientMessageId: vi.fn(() => "cmid_test"),
  };
});

import * as client from "../api/client";

const mockedCreate = vi.mocked(client.createConversation);
const mockedSend = vi.mocked(client.sendMessage);

// Captured stream callback so tests can drive events after render.
let capturedOnEvent: ((event: StreamEvent) => void) | null = null;
let resolveSend: (() => void) | null = null;

function Harness() {
  const c = useConversation();
  return (
    <ConversationView
      welcome={c.welcome}
      messages={c.messages}
      status={c.status}
      error={c.error}
      canSend={c.canSend}
      onSend={c.send}
      onSelectAction={() => {}}
      onRetry={c.retryLast}
      onRate={c.rate}
      onDismissError={c.clearError}
    />
  );
}

/** Render, wait for the conversation to be created, then send `text`. */
async function renderAndSend(text: string) {
  render(<Harness />);
  await screen.findByText("How can I help?");

  const input = screen.getByLabelText("Message");
  fireEvent.change(input, { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: /send message/i }));
  return input;
}

beforeEach(() => {
  capturedOnEvent = null;
  resolveSend = null;

  mockedCreate.mockResolvedValue({
    conversation_id: "cnv_1",
    session_token: "tok_1",
    welcome: { text: "How can I help?", suggested_actions: [] },
  });

  // Hold the stream open until the test resolves it; capture onEvent to drive frames.
  mockedSend.mockImplementation((_cid, _token, _content, _cmid, onEvent) => {
    capturedOnEvent = onEvent;
    return new Promise<void>((resolve) => {
      resolveSend = resolve;
    });
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("useConversation streaming", () => {
  it("appends deltas progressively and renders suggested actions on completion", async () => {
    const input = await renderAndSend("hello");

    // Composer locks while the response streams.
    expect(input).toBeDisabled();

    act(() => capturedOnEvent!({ event: "response.delta", data: { text: "Hel" } }));
    expect(screen.getByText("Hel")).toBeInTheDocument();

    act(() => capturedOnEvent!({ event: "response.delta", data: { text: "lo there" } }));
    expect(screen.getByText("Hello there")).toBeInTheDocument();

    act(() =>
      capturedOnEvent!({
        event: "response.completed",
        data: {
          assistant_message_id: "msg_1",
          suggested_actions: [{ id: "act_call", label: "Book a strategy call" }],
        },
      }),
    );

    expect(
      screen.getByRole("button", { name: "Book a strategy call" }),
    ).toBeInTheDocument();
    // Composer re-enables once the turn completes.
    expect(input).not.toBeDisabled();
  });
});

describe("useConversation busy lockout", () => {
  it("disables the composer while status is streaming", async () => {
    const input = await renderAndSend("are you there");
    const sendButton = screen.getByRole("button", { name: /send message/i });

    expect(input).toBeDisabled();
    expect(sendButton).toBeDisabled();

    act(() => capturedOnEvent!({ event: "response.completed", data: { assistant_message_id: "msg_9" } }));
    expect(input).not.toBeDisabled();
  });
});

describe("useConversation errors and cap", () => {
  it("keeps partial text and offers retry on response.failed", async () => {
    await renderAndSend("tell me more");

    act(() => capturedOnEvent!({ event: "response.delta", data: { text: "Partial answer" } }));
    act(() => capturedOnEvent!({ event: "response.failed", data: { code: "GENERATION_FAILED" } }));

    // Partial text stays visible.
    expect(screen.getByText("Partial answer")).toBeInTheDocument();
    // General-failure copy is shown.
    expect(screen.getByText(ERROR_COPY.generalFailure)).toBeInTheDocument();
    // Retry is offered and re-runs the same turn (same client_message_id).
    const retry = screen.getByRole("button", { name: "Retry" });
    fireEvent.click(retry);

    await waitFor(() =>
      expect(mockedSend).toHaveBeenLastCalledWith(
        "cnv_1",
        "tok_1",
        "tell me more",
        "cmid_test",
        expect.any(Function),
        expect.any(AbortSignal),
      ),
    );
    expect(mockedSend).toHaveBeenCalledTimes(2);
  });

  it("shows the cap copy and removes the placeholder on limit.reached", async () => {
    const input = await renderAndSend("one more question");

    act(() => capturedOnEvent!({ event: "limit.reached", data: {} }));

    expect(screen.getByText(ERROR_COPY.cap)).toBeInTheDocument();
    // No retry for the cap; the composer is usable again (status back to ready).
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(input).not.toBeDisabled();
  });

  it("marks the turn failed when the stream closes with no terminal event", async () => {
    await renderAndSend("hello");
    act(() => capturedOnEvent!({ event: "response.delta", data: { text: "Partial" } }));
    // Clean close with NO response.completed/failed/limit (a proxy/LB drop).
    await act(async () => {
      resolveSend?.();
    });
    expect(screen.getByText("Partial")).toBeInTheDocument();
    expect(screen.getByText(ERROR_COPY.generalFailure)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});

describe("useConversation guards", () => {
  it("blocks over-long messages with the too-long copy and does not call the API", async () => {
    render(<Harness />);
    await screen.findByText("How can I help?");

    const input = screen.getByLabelText("Message");
    const longText = "x".repeat(2001);
    fireEvent.change(input, { target: { value: longText } });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    expect(screen.getByText(ERROR_COPY.tooLong)).toBeInTheDocument();
    expect(mockedSend).not.toHaveBeenCalled();
  });

  it("keeps resolveSend usable so the stream promise can settle without error", async () => {
    await renderAndSend("hi");
    act(() => capturedOnEvent!({ event: "response.completed", data: { assistant_message_id: "m" } }));
    // Resolving the underlying send promise must not throw or set an error.
    await act(async () => {
      resolveSend?.();
    });
    expect(screen.queryByText(ERROR_COPY.generalFailure)).not.toBeInTheDocument();
  });
});
