// Tests for the safe assistant Markdown renderer.

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "./markdown";

function html(text: string): string {
  return render(<Markdown text={text} />).container.innerHTML;
}

function el(text: string) {
  return render(<Markdown text={text} />).container;
}

describe("Markdown renderer", () => {
  it("renders **bold**", () => {
    const c = el("**AI Strategy** matters");
    expect(c.querySelector("strong")?.textContent).toBe("AI Strategy");
    expect(c.textContent).toBe("AI Strategy matters");
  });

  it("renders *italic*", () => {
    expect(el("say *hi* now").querySelector("em")?.textContent).toBe("hi");
  });

  it("renders bold containing a nested italic", () => {
    const strong = el("**bold *inner***").querySelector("strong");
    expect(strong?.querySelector("em")?.textContent).toBe("inner");
    expect(strong?.textContent).toBe("bold inner");
  });

  it("renders `inline code` verbatim", () => {
    const code = el("use `npm run **x**` here").querySelector("code");
    expect(code?.textContent).toBe("npm run **x**"); // no formatting inside code
  });

  it("renders a safe link with target/rel", () => {
    const a = el("see [docs](https://cadre.ai/x)").querySelector("a");
    expect(a?.getAttribute("href")).toBe("https://cadre.ai/x");
    expect(a?.getAttribute("target")).toBe("_blank");
    expect(a?.getAttribute("rel")).toContain("noopener");
    expect(a?.textContent).toBe("docs");
  });

  it("drops an unsafe link scheme but keeps the text", () => {
    const c = el("[click](javascript:alert(1))");
    expect(c.querySelector("a")).toBeNull(); // never renders a javascript: link
    expect(c.textContent).toContain("click");
  });

  it("renders an unordered list", () => {
    const c = el("- one\n- two\n- three");
    const items = c.querySelectorAll("ul.cadre-md-ul > li");
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toBe("one");
    expect(items[2].textContent).toBe("three");
  });

  it("renders an ordered list", () => {
    const items = el("1. first\n2. second").querySelectorAll("ol.cadre-md-ol > li");
    expect(items).toHaveLength(2);
    expect(items[1].textContent).toBe("second");
  });

  it("splits blank-line-separated paragraphs and keeps soft breaks", () => {
    const c = el("line one\nline two\n\nsecond para");
    expect(c.querySelectorAll("p")).toHaveLength(2);
    expect(c.querySelector("p")?.querySelectorAll("br")).toHaveLength(1);
  });

  it("does NOT emphasise spaced asterisks like '$5 * 3 * 2'", () => {
    const c = el("$5 * 3 * 2");
    expect(c.querySelector("em")).toBeNull();
    expect(c.querySelector("strong")).toBeNull();
    expect(c.textContent).toBe("$5 * 3 * 2");
  });

  it("leaves an unclosed bold marker (mid-stream) as literal text", () => {
    const c = el("Cadre has:\n\n- **AI");
    expect(c.querySelector("strong")).toBeNull();
    expect(c.querySelector("li")?.textContent).toBe("**AI");
  });

  it("strips heading markers", () => {
    const c = el("# Overview");
    expect(c.textContent).toBe("Overview");
    expect(html("# Overview")).not.toContain("#");
  });

  it("renders nothing for empty content", () => {
    expect(html("")).toBe("");
  });

  it("renders the real four-services example (list + bold labels)", () => {
    const text = [
      "Cadre has four core services, and the right one depends on where you are:",
      "",
      "- **AI Strategy** — if you need to identify opportunities and build a roadmap.",
      "- **AI Leadership & Facilitation** — if your team needs alignment.",
      "- **AI Engineering** — if you're ready to build production AI workflows.",
      "- **AI Agents** — if you want systems that perform defined tasks.",
      "",
      "If you're not sure yet, the usual starting point is AI Strategy.",
    ].join("\n");

    const c = el(text);
    expect(c.querySelectorAll("p")).toHaveLength(2);
    const items = c.querySelectorAll("ul > li");
    expect(items).toHaveLength(4);
    const labels = Array.from(c.querySelectorAll("ul > li strong")).map((s) => s.textContent);
    expect(labels).toEqual([
      "AI Strategy",
      "AI Leadership & Facilitation",
      "AI Engineering",
      "AI Agents",
    ]);
    // No stray literal markdown markers survive.
    expect(c.textContent).not.toContain("**");
  });
});
