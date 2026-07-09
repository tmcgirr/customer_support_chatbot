// Auto-grow behaviour for the composer textarea. jsdom has no layout engine, so we
// stub scrollHeight to simulate content of a given rendered height and assert the
// component grows to fit, then holds a constant capped height + scrolls past the
// row limit. The exact cap depends on the computed line-height, so the cap tests
// assert the behaviour relatively rather than pinning a pixel value.

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Composer } from "./Composer";

function stubScrollHeight(px: number) {
  Object.defineProperty(HTMLTextAreaElement.prototype, "scrollHeight", {
    configurable: true,
    get: () => px,
  });
}

afterEach(() => {
  delete (HTMLTextAreaElement.prototype as unknown as { scrollHeight?: number }).scrollHeight;
});

describe("Composer auto-grow", () => {
  it("grows to fit content below the cap without scrolling", () => {
    render(<Composer onSend={vi.fn()} />);
    const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement;

    stubScrollHeight(58); // ~2 lines, comfortably under the cap
    fireEvent.change(textarea, { target: { value: "line one\nline two" } });

    expect(textarea.style.height).toBe("58px");
    expect(textarea.style.overflowY).toBe("hidden");
  });

  it("holds a constant capped height and scrolls past the row limit", () => {
    render(<Composer onSend={vi.fn()} />);
    const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement;

    stubScrollHeight(240);
    fireEvent.change(textarea, { target: { value: "a\nb\nc\nd\ne\nf" } });
    const capped = textarea.style.height;
    expect(textarea.style.overflowY).toBe("auto");
    expect(parseFloat(capped)).toBeLessThan(240); // capped below content height

    // Even taller content does not grow the box further.
    stubScrollHeight(500);
    fireEvent.change(textarea, { target: { value: "a\nb\nc\nd\ne\nf\ng\nh" } });
    expect(textarea.style.height).toBe(capped);
    expect(textarea.style.overflowY).toBe("auto");
  });

  it("shrinks back to a single line after sending", () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} />);
    const textarea = screen.getByLabelText("Message") as HTMLTextAreaElement;

    stubScrollHeight(240);
    fireEvent.change(textarea, { target: { value: "a\nb\nc\nd\ne" } });
    expect(textarea.style.overflowY).toBe("auto");

    stubScrollHeight(37); // one line once cleared
    fireEvent.submit(textarea.closest("form")!);

    expect(onSend).toHaveBeenCalledWith("a\nb\nc\nd\ne");
    expect(textarea.value).toBe("");
    expect(textarea.style.height).toBe("37px");
    expect(textarea.style.overflowY).toBe("hidden");
  });
});
