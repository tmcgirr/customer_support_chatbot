// Auto-scroll behaviour for the transcript, matching the "standard chatbot" feel:
//
//  - On SEND, the just-sent user message rolls up to the top of the viewport, leaving
//    room below for the "thinking" indicator and the streaming reply (a bottom spacer
//    guarantees there is room even when the reply is short).
//  - While the reply STREAMS, once it grows enough to fill the viewport the view
//    follows the bottom so the newest text stays visible — but only if the user is
//    still near the bottom (scrolling up to read pauses the follow).
//  - On initial load / resume, jump straight to the latest message.
//
// jsdom has no layout engine, so the decision is factored into a pure `decideScroll`
// that is unit-tested; the hook only measures the DOM and applies the result.

import { useLayoutEffect, useRef } from "react";
import type { RefObject } from "react";

import type { ChatMessage } from "../types";
import type { ConversationStatus } from "./useConversation";

const PAD = 14; // gap left above the anchored user message
const NEAR = 100; // px within the bottom that still counts as "following"

export type ScrollAction =
  | { kind: "anchorTop"; top: number }
  | { kind: "bottom" }
  | { kind: "none" };

export interface ScrollInput {
  prevCount: number;
  count: number;
  isNewUserTurn: boolean;
  streaming: boolean;
  hasUser: boolean;
  userTop: number;
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
  /** Whether the bottom spacer is (or will be) collapsed to 0 — i.e. real content
      fills the viewport, so following the bottom is meaningful. */
  spacerCollapsed: boolean;
  pad?: number;
  near?: number;
}

export function decideScroll(input: ScrollInput): ScrollAction {
  const pad = input.pad ?? PAD;
  const near = input.near ?? NEAR;

  // A freshly sent message rolls to the top (takes priority over everything).
  if (input.isNewUserTurn && input.streaming && input.hasUser) {
    return { kind: "anchorTop", top: Math.max(0, input.userTop - pad) };
  }
  // First paint of a loaded/resumed transcript: show the latest message.
  if (input.prevCount === 0 && input.count > 0) {
    return { kind: "bottom" };
  }
  // Follow the streaming tail while the user is pinned near the bottom AND the
  // content itself (not the spacer) fills the viewport.
  const nearBottom = input.scrollHeight - input.scrollTop - input.clientHeight <= near;
  if (nearBottom && input.spacerCollapsed) {
    return { kind: "bottom" };
  }
  return { kind: "none" };
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;
}

function lastUserId(messages: ChatMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].role === "user") return messages[i].id;
  }
  return null;
}

export function useConversationScroll(
  scrollRef: RefObject<HTMLElement>,
  spacerRef: RefObject<HTMLElement>,
  messages: ChatMessage[],
  status: ConversationStatus,
): void {
  const lastUserIdRef = useRef<string | null>(null);
  const prevCountRef = useRef(0);

  useLayoutEffect(() => {
    const c = scrollRef.current;
    if (!c) return;
    const spacer = spacerRef.current;

    const prevCount = prevCountRef.current;
    prevCountRef.current = messages.length;

    const scrollTop = c.scrollTop;
    const clientHeight = c.clientHeight;

    // Position of the last user message within the scroll content.
    const userNodes = c.querySelectorAll<HTMLElement>(".cadre-message-user");
    const userEl = userNodes[userNodes.length - 1];
    const hasUser = !!userEl;
    let userTop = 0;
    if (userEl) {
      const containerTop = c.getBoundingClientRect().top;
      userTop = userEl.getBoundingClientRect().top - containerTop + scrollTop;
    }

    // Size the bottom spacer so the last user message can reach the top with the
    // content below it filling (at most) the viewport.
    let spacerCollapsed = true;
    if (spacer) {
      const contentBelow = c.scrollHeight - spacer.offsetHeight - userTop;
      const desired = hasUser ? Math.max(0, clientHeight - PAD - contentBelow) : 0;
      spacer.style.height = `${desired}px`;
      spacerCollapsed = desired === 0;
    }

    const currentLastUser = lastUserId(messages);
    const isNewUserTurn = currentLastUser !== null && currentLastUser !== lastUserIdRef.current;
    if (currentLastUser !== null) lastUserIdRef.current = currentLastUser;

    const action = decideScroll({
      prevCount,
      count: messages.length,
      isNewUserTurn,
      streaming: status === "streaming",
      hasUser,
      userTop,
      scrollTop,
      scrollHeight: c.scrollHeight,
      clientHeight,
      spacerCollapsed,
    });

    if (action.kind === "anchorTop") {
      const behavior: ScrollBehavior = prefersReducedMotion() ? "auto" : "smooth";
      if (typeof c.scrollTo === "function") {
        c.scrollTo({ top: action.top, behavior });
      } else {
        c.scrollTop = action.top;
      }
    } else if (action.kind === "bottom") {
      c.scrollTop = c.scrollHeight;
    }
  }, [messages, status, scrollRef, spacerRef]);
}
