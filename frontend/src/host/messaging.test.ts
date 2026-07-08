import { afterEach, describe, expect, it, vi } from "vitest";

// Pin a concrete allow-list so origin/source filtering is deterministic (the real
// config defaults to "*", which would allow everything).
vi.mock("../config", () => ({
  ALLOWED_HOST_ORIGINS: ["https://host.example"],
}));

import { listenToHost, postToHost } from "./messaging";

const ALLOWED = "https://host.example";

function dispatch(data: unknown, origin: string): void {
  window.dispatchEvent(new MessageEvent("message", { data, origin }));
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("listenToHost", () => {
  it("invokes the handler for a trusted origin + cadre-host source", () => {
    const handler = vi.fn();
    const off = listenToHost(handler);

    dispatch({ source: "cadre-host", type: "host.ready", payload: { a: 1 } }, ALLOWED);

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith("host.ready", { a: 1 });
    off();
  });

  it("ignores events from a disallowed origin", () => {
    const handler = vi.fn();
    const off = listenToHost(handler);

    dispatch({ source: "cadre-host", type: "host.ready" }, "https://evil.example");

    expect(handler).not.toHaveBeenCalled();
    off();
  });

  it("ignores events whose source is not cadre-host", () => {
    const handler = vi.fn();
    const off = listenToHost(handler);

    dispatch({ source: "someone-else", type: "host.ready" }, ALLOWED);
    dispatch({ type: "host.ready" }, ALLOWED); // no source at all
    dispatch("not-an-object", ALLOWED);

    expect(handler).not.toHaveBeenCalled();
    off();
  });

  it("stops invoking the handler after unsubscribe", () => {
    const handler = vi.fn();
    const off = listenToHost(handler);
    off();

    dispatch({ source: "cadre-host", type: "host.ready" }, ALLOWED);

    expect(handler).not.toHaveBeenCalled();
  });
});

describe("postToHost", () => {
  it("posts a stamped envelope to each configured origin (never '*')", () => {
    const spy = vi.spyOn(window.parent, "postMessage");

    postToHost("widget.open", { height: 100 });

    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith(
      { source: "cadre-widget", type: "widget.open", payload: { height: 100 } },
      ALLOWED,
    );
  });
});
