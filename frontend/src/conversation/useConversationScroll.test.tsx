// Unit tests for the pure scroll-decision function. jsdom has no layout, so the
// hook's DOM measurement is not exercised here; the branch logic (which is where the
// behaviour lives) is.

import { describe, expect, it } from "vitest";

import { decideScroll } from "./useConversationScroll";
import type { ScrollInput } from "./useConversationScroll";

const base: ScrollInput = {
  prevCount: 2,
  count: 3,
  isNewUserTurn: false,
  streaming: false,
  hasUser: true,
  userTop: 500,
  scrollTop: 0,
  scrollHeight: 1000,
  clientHeight: 400,
  spacerCollapsed: true,
  pad: 14,
  near: 100,
};

describe("decideScroll", () => {
  it("rolls a just-sent message to the top while streaming", () => {
    expect(decideScroll({ ...base, isNewUserTurn: true, streaming: true, userTop: 500 })).toEqual({
      kind: "anchorTop",
      top: 486, // userTop - pad
    });
  });

  it("clamps the anchor to 0 when the message is already near the top", () => {
    const action = decideScroll({ ...base, isNewUserTurn: true, streaming: true, userTop: 6 });
    expect(action).toEqual({ kind: "anchorTop", top: 0 });
  });

  it("does not anchor a 'new last user' that is a resume, not a send (not streaming)", () => {
    // prevCount 0 -> a freshly loaded transcript whose last user id is 'new'.
    const action = decideScroll({
      ...base,
      prevCount: 0,
      isNewUserTurn: true,
      streaming: false,
    });
    expect(action).toEqual({ kind: "bottom" });
  });

  it("jumps to the bottom on first paint of a loaded transcript", () => {
    expect(decideScroll({ ...base, prevCount: 0, count: 4 })).toEqual({ kind: "bottom" });
  });

  it("follows the streaming tail when near the bottom and the spacer has collapsed", () => {
    const action = decideScroll({
      ...base,
      streaming: true,
      scrollTop: 605, // scrollHeight(1000) - clientHeight(400) = 600 -> within 100 of bottom
      spacerCollapsed: true,
    });
    expect(action).toEqual({ kind: "bottom" });
  });

  it("does NOT follow while the message is still anchored at the top (spacer not collapsed)", () => {
    // Even though the anchored position reads as 'near the bottom' of the padded
    // content, an uncollapsed spacer means real content hasn't filled the viewport yet.
    const action = decideScroll({
      ...base,
      streaming: true,
      scrollTop: 590,
      spacerCollapsed: false,
    });
    expect(action).toEqual({ kind: "none" });
  });

  it("does NOT yank the view down when the user has scrolled up", () => {
    const action = decideScroll({
      ...base,
      streaming: true,
      scrollTop: 100, // far from the bottom (600)
      spacerCollapsed: true,
    });
    expect(action).toEqual({ kind: "none" });
  });
});
