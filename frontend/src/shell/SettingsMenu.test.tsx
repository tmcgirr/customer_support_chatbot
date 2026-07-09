// Accessibility settings menu: applies the text-size scale to the widget root,
// persists across remounts, stays axe-clean while open, and Esc closes the menu
// without closing the whole panel.

import { fireEvent, render, screen } from "@testing-library/react";
import { axe, toHaveNoViolations } from "jest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WidgetFrame } from "./WidgetFrame";

vi.mock("../host/messaging", () => ({
  postToHost: vi.fn(),
  listenToHost: vi.fn(() => () => {}),
}));

expect.extend(toHaveNoViolations);

// The test runtime's built-in localStorage is a partial shim; swap in a simple
// in-memory Storage so persistence is deterministic and isolated per test.
beforeEach(() => {
  const store = new Map<string, string>();
  const mock: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key) => (store.has(key) ? (store.get(key) as string) : null),
    key: (index) => Array.from(store.keys())[index] ?? null,
    removeItem: (key) => {
      store.delete(key);
    },
    setItem: (key, value) => {
      store.set(key, String(value));
    },
  };
  Object.defineProperty(window, "localStorage", { configurable: true, value: mock });
});

function renderOpenWidget(onClose = vi.fn()) {
  const utils = render(
    <WidgetFrame open onToggle={vi.fn()} onClose={onClose}>
      <div>conversation</div>
    </WidgetFrame>,
  );
  const root = utils.container.querySelector(".cadre-widget") as HTMLElement;
  return { ...utils, root, onClose };
}

describe("accessibility settings menu", () => {
  it("applies the chosen text size to the widget root", () => {
    const { root } = renderOpenWidget();
    expect(root.style.getPropertyValue("--cadre-font-scale")).toBe("1");

    fireEvent.click(screen.getByRole("button", { name: "Accessibility settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Larger text size" }));
    expect(root.style.getPropertyValue("--cadre-font-scale")).toBe("1.3");
  });

  it("persists the choice across remounts", () => {
    const first = renderOpenWidget();
    fireEvent.click(screen.getByRole("button", { name: "Accessibility settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Large text size" }));
    first.unmount();

    const { root } = renderOpenWidget();
    expect(root.style.getPropertyValue("--cadre-font-scale")).toBe("1.15");
  });

  it("has no axe violations with the menu open", async () => {
    const { container } = renderOpenWidget();
    fireEvent.click(screen.getByRole("button", { name: "Accessibility settings" }));
    expect(
      await axe(container, { rules: { region: { enabled: false } } }),
    ).toHaveNoViolations();
  });

  it("closes on Escape without closing the panel", () => {
    const { onClose } = renderOpenWidget();
    const trigger = screen.getByRole("button", { name: "Accessibility settings" });

    fireEvent.click(trigger);
    expect(
      screen.getByRole("group", { name: "Accessibility settings" }),
    ).toBeInTheDocument();

    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(
      screen.queryByRole("group", { name: "Accessibility settings" }),
    ).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});
