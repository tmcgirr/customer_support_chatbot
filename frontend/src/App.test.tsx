import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

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
  it("opens the panel and shows the welcome + suggested chips", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Chat with us" }));

    expect(await screen.findByText(/Cadre AI's virtual assistant/i)).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "Book a strategy call" }),
    ).toBeInTheDocument();
  });

  it("opens the strategy-call form when its chip is selected (side effects via a form)", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Chat with us" }));
    fireEvent.click(await screen.findByRole("button", { name: "Book a strategy call" }));

    expect(
      await screen.findByText(/request a conversation with an AI strategist/i),
    ).toBeInTheDocument();
  });
});
