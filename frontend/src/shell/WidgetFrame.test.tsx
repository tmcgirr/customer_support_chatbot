import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { postToHost } from "../host/messaging";
import { WidgetFrame } from "./WidgetFrame";

// Stub the host bridge so tests don't post real cross-window messages and we can
// assert the open/close signals.
vi.mock("../host/messaging", () => ({
  postToHost: vi.fn(),
  listenToHost: vi.fn(() => () => {}),
}));

/** Stateful harness so the controlled `open` prop actually toggles. */
function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <WidgetFrame
      open={open}
      onToggle={() => setOpen((prev) => !prev)}
      onClose={() => setOpen(false)}
    >
      <p>conversation goes here</p>
      <button type="button">a focusable child</button>
    </WidgetFrame>
  );
}

beforeEach(() => {
  vi.mocked(postToHost).mockClear();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("WidgetFrame", () => {
  it("shows only the launcher until opened", () => {
    render(<Harness />);

    expect(screen.getByRole("button", { name: "Chat with us" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("toggles the panel open and closed from the launcher", () => {
    render(<Harness />);
    const launcher = screen.getByRole("button", { name: "Chat with us" });

    fireEvent.click(launcher);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveFocus(); // focus moved into the panel
    expect(postToHost).toHaveBeenCalledWith("widget.open", expect.any(Object));

    // The launcher now reflects the open state.
    const closeLauncher = screen.getByRole("button", { name: "Close chat", expanded: true });
    fireEvent.click(closeLauncher);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(postToHost).toHaveBeenCalledWith("widget.close", expect.any(Object));
  });

  it("closes the panel on Escape and restores focus to the launcher", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Chat with us" }));

    const dialog = screen.getByRole("dialog");
    fireEvent.keyDown(dialog, { key: "Escape" });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Chat with us" })).toHaveFocus();
  });

  it("closes the panel from the header close button", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Chat with us" }));

    // Scope to the dialog: the open launcher is also named "Close chat".
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Close chat" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders the header and children when open", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Chat with us" }));

    expect(screen.getByText("Cadre AI Assistant")).toBeInTheDocument();
    expect(screen.getByText("conversation goes here")).toBeInTheDocument();
    // The privacy disclosure is no longer a persistent footer here; it now lives in
    // the opening/welcome message (see App.test / WelcomeChips).
  });

  it("fires onNewChat from the header New chat button and disables it when not allowed", () => {
    const onNewChat = vi.fn();
    const { rerender } = render(
      <WidgetFrame open onToggle={vi.fn()} onClose={vi.fn()} onNewChat={onNewChat} canStartNew>
        <p>body</p>
      </WidgetFrame>,
    );

    const newChat = screen.getByRole("button", { name: "New chat" });
    expect(newChat).toBeEnabled();
    fireEvent.click(newChat);
    expect(onNewChat).toHaveBeenCalledTimes(1);

    rerender(
      <WidgetFrame
        open
        onToggle={vi.fn()}
        onClose={vi.fn()}
        onNewChat={onNewChat}
        canStartNew={false}
      >
        <p>body</p>
      </WidgetFrame>,
    );
    expect(screen.getByRole("button", { name: "New chat" })).toBeDisabled();
  });
});
