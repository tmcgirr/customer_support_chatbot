import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { createConversation } from "./api/client";

vi.mock("./api/client", () => ({
  createConversation: vi.fn().mockResolvedValue({
    conversation_id: "cnv_1",
    session_token: "tok",
    welcome: {
      text: "Hi, I'm Cadre AI's virtual assistant.",
      suggested_actions: [
        { id: "company_overview", label: "What does Cadre AI do?" },
        { id: "strategy_call", label: "Book a strategy call" },
      ],
    },
  }),
  sendMessage: vi.fn(),
  submitRequest: vi.fn(),
  submitFeedback: vi.fn(),
  newClientMessageId: () => "cmid_test",
  ApiError: class ApiError extends Error {},
}));

afterEach(() => vi.clearAllMocks());

describe("widget integration", () => {
  it("shows the welcome + suggested chips (panel open by default)", async () => {
    render(<App />);

    expect(await screen.findByText(/Cadre AI's virtual assistant/i)).toBeInTheDocument();
    // The privacy disclosure is shown once in the opening message (not a footer).
    expect(
      screen.getByText(/This chat uses AI and may store your messages/i),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "Book a strategy call" }),
    ).toBeInTheDocument();
  });

  it("starts a fresh chat from the header New chat button", async () => {
    render(<App />);
    await screen.findByText(/Cadre AI's virtual assistant/i);
    // One create on boot.
    expect(createConversation).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "New chat" }));

    // A second create for the fresh thread, and the welcome is shown again.
    await waitFor(() => expect(createConversation).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/Cadre AI's virtual assistant/i)).toBeInTheDocument();
  });

  it("opens the strategy-call form when its chip is selected (side effects via a form)", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Book a strategy call" }));

    expect(
      await screen.findByText(/request a conversation with an AI strategist/i),
    ).toBeInTheDocument();
  });
});
