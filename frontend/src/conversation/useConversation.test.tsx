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
    getTranscript: vi.fn(),
    submitFeedback: vi.fn(),
    newClientMessageId: vi.fn(() => "cmid_test"),
  };
});

import * as client from "../api/client";

const mockedCreate = vi.mocked(client.createConversation);
const mockedSend = vi.mocked(client.sendMessage);
const mockedTranscript = vi.mocked(client.getTranscript);
const mockedCmid = vi.mocked(client.newClientMessageId);

// Captured stream callback so tests can drive events after render.
let capturedOnEvent: ((event: StreamEvent) => void) | null = null;
let resolveSend: (() => void) | null = null;
let rejectSend: ((err: unknown) => void) | null = null;

function Harness() {
  const c = useConversation();
  return (
    <>
      {/* Test-only affordance to invoke startNew from any state (the header button
          that drives it in the app lives in the shell, not this view). */}
      <button type="button" data-testid="test-start-new" onClick={c.startNew}>
        test-start-new
      </button>
      <ConversationView
        welcome={c.welcome}
        messages={c.messages}
        status={c.status}
        error={c.error}
        canSend={c.canSend}
        onSend={c.send}
        onSelectAction={() => {}}
        onRetry={c.retryLast}
        onReconnect={c.reconnect}
        onStartNew={c.startNew}
        onRate={c.rate}
        onDismissError={c.clearError}
      />
    </>
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

  // Hold the stream open until the test resolves/rejects it; capture onEvent for frames.
  mockedSend.mockImplementation((_cid, _token, _content, _cmid, onEvent) => {
    capturedOnEvent = onEvent;
    return new Promise<void>((resolve, reject) => {
      resolveSend = resolve;
      rejectSend = reject;
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

  it("marks the turn failed when the stream drops and the transcript has no reply", async () => {
    // The reconcile fetch also fails (offline) → keep partial text, mark failed, retry.
    mockedTranscript.mockRejectedValue(new Error("network"));
    await renderAndSend("hello");
    act(() => capturedOnEvent!({ event: "response.delta", data: { text: "Partial" } }));
    // Clean close with NO response.completed/failed/limit (a proxy/LB drop).
    await act(async () => {
      resolveSend?.();
    });
    await waitFor(() =>
      expect(screen.getByText(ERROR_COPY.generalFailure)).toBeInTheDocument(),
    );
    expect(screen.getByText("Partial")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("reconciles to the completed answer when a dropped turn actually finished", async () => {
    // The SSE frame was lost but the server persisted a completed reply.
    mockedTranscript.mockResolvedValue({
      conversation_id: "cnv_1",
      messages: [
        { id: "u1", role: "user", content: "hello", status: "completed", suggested_action_ids: [] },
        {
          id: "a1",
          role: "assistant",
          content: "Full answer from the server.",
          status: "completed",
          suggested_action_ids: [],
        },
      ],
    });
    await renderAndSend("hello");
    act(() => capturedOnEvent!({ event: "response.delta", data: { text: "Full ans" } }));
    await act(async () => {
      resolveSend?.();
    });
    // The authoritative transcript replaces the partial stream; no error surfaces.
    await waitFor(() =>
      expect(screen.getByText("Full answer from the server.")).toBeInTheDocument(),
    );
    expect(screen.queryByText(ERROR_COPY.generalFailure)).not.toBeInTheDocument();
  });
});

describe("useConversation reconnect", () => {
  it("resumes a stored session from the transcript instead of creating a new one", async () => {
    // Simulate a page reload: a prior session persisted in sessionStorage.
    window.sessionStorage.setItem(
      "cadre_widget_session_v1",
      JSON.stringify({ conversationId: "cnv_prev", token: "tok_prev" }),
    );
    mockedTranscript.mockResolvedValue({
      conversation_id: "cnv_prev",
      messages: [
        { id: "u1", role: "user", content: "earlier question", status: "completed", suggested_action_ids: [] },
        { id: "a1", role: "assistant", content: "earlier answer", status: "completed", suggested_action_ids: [] },
      ],
    });

    render(<Harness />);

    // The transcript is restored; no new conversation is created.
    await screen.findByText("earlier answer");
    expect(screen.getByText("earlier question")).toBeInTheDocument();
    expect(mockedTranscript).toHaveBeenCalledWith("cnv_prev", "tok_prev", expect.anything());
    expect(mockedCreate).not.toHaveBeenCalled();
  });

  it("starts fresh when the stored session has expired (401)", async () => {
    window.sessionStorage.setItem(
      "cadre_widget_session_v1",
      JSON.stringify({ conversationId: "cnv_old", token: "tok_old" }),
    );
    mockedTranscript.mockRejectedValue(
      new client.ApiError("UNAUTHORIZED_SESSION", "expired", false, 401),
    );

    render(<Harness />);

    // Falls back to a brand-new conversation (welcome shown).
    await screen.findByText("How can I help?");
    expect(mockedCreate).toHaveBeenCalledTimes(1);
  });
});

describe("useConversation recovery (review fixes)", () => {
  it("disables input and offers a working recovery when the initial create fails", async () => {
    mockedCreate.mockRejectedValueOnce(new Error("cold start")); // first create fails
    render(<Harness />);

    await screen.findByText(ERROR_COPY.startFailed);
    // No live session → the composer is disabled so a typed message can't be dropped.
    expect(screen.getByLabelText("Message")).toBeDisabled();
    // "Try again" actually re-creates the conversation (the default mock resolves).
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText("How can I help?");
    expect(screen.getByLabelText("Message")).not.toBeDisabled();
  });

  it("does not mark a dropped turn complete when only the PRIOR turn's reply exists", async () => {
    mockedCmid.mockReturnValueOnce("cmid_1").mockReturnValueOnce("cmid_2");
    const input = await renderAndSend("first");
    act(() => capturedOnEvent!({ event: "response.delta", data: { text: "answer one" } }));
    act(() => capturedOnEvent!({ event: "response.completed", data: { assistant_message_id: "a1" } }));
    await act(async () => {
      resolveSend?.();
    });

    // Turn 2 drops before persisting; the transcript still shows only turn 1's reply.
    mockedTranscript.mockResolvedValue({
      conversation_id: "cnv_1",
      messages: [
        { id: "u1", role: "user", content: "first", status: "completed", suggested_action_ids: [] },
        { id: "a1", role: "assistant", content: "answer one", status: "completed", suggested_action_ids: [] },
      ],
    });
    fireEvent.change(input, { target: { value: "second" } });
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));
    await act(async () => {
      resolveSend?.();
    });

    // The second question is NOT silently lost: it stays visible and retry is offered.
    await waitFor(() =>
      expect(screen.getByText(ERROR_COPY.generalFailure)).toBeInTheDocument(),
    );
    expect(screen.getByText("second")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("expires the session on a 401 mid-turn: clears the spinner and disables input", async () => {
    const input = await renderAndSend("hello");
    act(() => capturedOnEvent!({ event: "response.delta", data: { text: "partial" } }));
    await act(async () => {
      rejectSend?.(new client.ApiError("UNAUTHORIZED_SESSION", "expired", false, 401));
    });

    await screen.findByText(ERROR_COPY.sessionExpired);
    // Dead session → composer disabled, no stuck streaming placeholder, new-chat offered.
    expect(input).toBeDisabled();
    expect(screen.queryByText("partial")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start new chat" })).toBeInTheDocument();
  });

  it("starts fresh instead of a blank pane when the stored conversation is empty", async () => {
    window.sessionStorage.setItem(
      "cadre_widget_session_v1",
      JSON.stringify({ conversationId: "cnv_empty", token: "tok" }),
    );
    mockedTranscript.mockResolvedValue({ conversation_id: "cnv_empty", messages: [] });

    render(<Harness />);

    await screen.findByText("How can I help?"); // fresh create's welcome
    expect(mockedCreate).toHaveBeenCalledTimes(1);
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

describe("useConversation startNew", () => {
  it("starts a fresh chat mid-stream: aborts the turn, clears the transcript, re-enables input", async () => {
    const input = await renderAndSend("hello");
    act(() => capturedOnEvent!({ event: "response.delta", data: { text: "partial answer" } }));
    expect(screen.getByText("partial answer")).toBeInTheDocument();
    expect(input).toBeDisabled();

    // The fresh conversation gets its own id/token/welcome.
    mockedCreate.mockResolvedValueOnce({
      conversation_id: "cnv_2",
      session_token: "tok_2",
      welcome: { text: "How can I help?", suggested_actions: [] },
    });

    fireEvent.click(screen.getByTestId("test-start-new"));

    // Back to a clean welcome state: transcript wiped, a second create issued.
    await screen.findByText("How can I help?");
    expect(screen.queryByText("partial answer")).not.toBeInTheDocument();
    expect(mockedCreate).toHaveBeenCalledTimes(2);
    expect(screen.getByLabelText("Message")).not.toBeDisabled();

    // The aborted stream settling afterwards must not resurrect the old turn.
    await act(async () => {
      resolveSend?.();
    });
    expect(screen.queryByText("partial answer")).not.toBeInTheDocument();
    expect(screen.queryByText(ERROR_COPY.generalFailure)).not.toBeInTheDocument();
  });

  it("mid-stream new chat that fails to create lands clean (no stuck turn, composer disabled)", async () => {
    await renderAndSend("hello");
    act(() => capturedOnEvent!({ event: "response.delta", data: { text: "partial answer" } }));
    expect(screen.getByText("partial answer")).toBeInTheDocument();

    // The fresh create fails (cold start / blip).
    mockedCreate.mockRejectedValueOnce(new Error("cold start"));

    await act(async () => {
      fireEvent.click(screen.getByTestId("test-start-new"));
    });

    // The abandoned turn is gone (no stuck typing indicator), and because the old
    // session was cleared there is nothing to send into: the composer is disabled and
    // the only recovery is "Try again".
    expect(screen.queryByText("partial answer")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toBeDisabled();
    expect(screen.getByText(ERROR_COPY.startFailed)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
