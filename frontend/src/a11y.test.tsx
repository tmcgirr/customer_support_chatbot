// Automated accessibility checks for the chat widget's presentational + shell layer.
// Renders the OPEN widget in two representative states (empty/welcome and a
// completed assistant turn with citations, suggested actions, and feedback) and
// asserts axe-core finds no violations. This is a static ARIA/roles/names guard; it
// complements the behavioural focus/keyboard tests in WidgetFrame.test.tsx.

import type { ReactNode } from "react";
import { render } from "@testing-library/react";
import { axe, toHaveNoViolations } from "jest-axe";
import { describe, expect, it, vi } from "vitest";

import { ConversationView } from "./conversation/ConversationView";
import type { ChatMessage, WelcomePayload } from "./types";
import { WidgetFrame } from "./shell/WidgetFrame";

expect.extend(toHaveNoViolations);

// The shell posts open/close/resize messages to the host; stub the bridge so the
// axe render doesn't fire real cross-window messages.
vi.mock("./host/messaging", () => ({
  postToHost: vi.fn(),
  listenToHost: vi.fn(() => () => {}),
}));

const noop = () => {};

// Common no-op handlers for the presentational view.
const viewHandlers = {
  onSend: noop,
  onSelectAction: noop,
  onRetry: noop,
  onReconnect: noop,
  onStartNew: noop,
  onRate: noop,
  onDismissError: noop,
};

function renderOpenWidget(children: ReactNode) {
  return render(
    <WidgetFrame open onToggle={noop} onClose={noop}>
      {children}
    </WidgetFrame>,
  );
}

// "region" is an axe best-practice rule that expects all page content inside a
// landmark; we render a widget fragment (not a full document), so it does not apply.
const AXE_OPTIONS = { rules: { region: { enabled: false } } };

describe("widget accessibility (axe)", () => {
  it("has no violations in the welcome/empty state", async () => {
    const welcome: WelcomePayload = {
      text: "Hi, I'm Cadre AI's virtual assistant. How can I help?",
      suggested_actions: [
        { id: "company_overview", label: "What does Cadre AI do?" },
        { id: "strategy_call", label: "Book a strategy call" },
      ],
    };

    const { container } = renderOpenWidget(
      <ConversationView welcome={welcome} messages={[]} status="ready" error={null} canSend {...viewHandlers} />,
    );

    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });

  it("has no violations with a completed assistant turn (citations, actions, feedback)", async () => {
    const messages: ChatMessage[] = [
      {
        id: "u1",
        role: "user",
        content: "What does Cadre AI do?",
        status: "completed",
        suggestedActions: [],
      },
      {
        id: "a1",
        role: "assistant",
        content: "Cadre AI helps organisations build a practical AI strategy.",
        status: "completed",
        suggestedActions: [
          { id: "strategy_call", label: "Book a strategy call" },
          { id: "human_escalation", label: "Talk to a person" },
        ],
        sources: [{ title: "Cadre AI overview", url: "https://example.com/overview" }],
      },
    ];

    const { container } = renderOpenWidget(
      <ConversationView welcome={null} messages={messages} status="ready" error={null} canSend {...viewHandlers} />,
    );

    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });
});
