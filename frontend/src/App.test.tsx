import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

type Listener = (event: { data: string }) => void;

/** Minimal EventSource stand-in the test drives manually. */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  onerror: (() => void) | null = null;
  closed = false;
  private listeners: Record<string, Listener[]> = {};

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(name: string, fn: Listener) {
    (this.listeners[name] ??= []).push(fn);
  }

  emit(name: string, data: unknown) {
    const event = { data: JSON.stringify(data) };
    (this.listeners[name] ?? []).forEach((fn) => fn(event));
  }

  close() {
    this.closed = true;
  }
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App walking skeleton", () => {
  it("connects to the stream-test endpoint and renders deltas progressively", () => {
    render(<App />);
    const source = FakeEventSource.instances[0];
    expect(source.url).toContain("/api/v1/dev/stream-test");

    act(() => source.emit("response.started", {}));
    expect(screen.getByTestId("status").textContent).toContain("streaming");

    act(() => source.emit("response.delta", { index: 0, text: "Hello " }));
    expect(screen.getByTestId("stream").textContent).toBe("Hello ");

    act(() => source.emit("response.delta", { index: 1, text: "world" }));
    expect(screen.getByTestId("stream").textContent).toBe("Hello world");

    act(() => source.emit("response.completed", { delta_count: 2 }));
    expect(screen.getByTestId("status").textContent).toContain("completed");
    expect(source.closed).toBe(true);
  });
});
