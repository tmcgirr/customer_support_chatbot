import { useCallback, useEffect, useLayoutEffect, useRef } from "react";
import type {
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  ReactNode,
  RefObject,
} from "react";

import { postToHost } from "../host/messaging";
import { Launcher } from "./Launcher";
import { FONT_SCALE_VALUE, useAccessibilityPrefs } from "./useAccessibilityPrefs";
import { WidgetHeader } from "./WidgetHeader";
// Import the shared styles from the component so the shell is styled wherever it
// renders, independent of whoever owns the app entrypoint.
import "../index.css";

export interface WidgetFrameProps {
  /** Whether the chat panel is open. */
  open: boolean;
  /** Toggle the panel (fired by the launcher). */
  onToggle: () => void;
  /** Close the panel (fired by the header close button and Esc). */
  onClose: () => void;
  /** Start a fresh conversation (new thread, cleared transcript) from the header. */
  onNewChat?: () => void;
  /** Whether starting a new chat is currently allowed (disabled during boot/reconnect). */
  canStartNew?: boolean;
  /** Panel body — the conversation view / forms rendered by sibling modules. */
  children: ReactNode;
  /**
   * Element to focus when the panel opens (e.g. the composer input) so a keyboard or
   * screen-reader user lands ready to type. Falls back to the dialog container when
   * absent or currently disabled (e.g. while the conversation is still connecting).
   */
  initialFocusRef?: RefObject<HTMLElement>;
}

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "textarea:not([disabled])",
  'input:not([disabled]):not([type="hidden"])',
  "select:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

/**
 * Outer chrome for the widget: the floating launcher plus the chat panel.
 *
 * Responsibilities:
 * - Renders the launcher always; renders the panel (header + scrollable content)
 *   only while `open`. The privacy disclosure now lives in the opening message.
 * - Notifies the host of open/close/resize via origin-checked postMessage.
 * - Traps Tab focus inside the panel, moves focus in on open, restores it to the
 *   launcher on close, and closes on Esc.
 */
export function WidgetFrame({
  open,
  onToggle,
  onClose,
  onNewChat,
  canStartNew = true,
  children,
  initialFocusRef,
}: WidgetFrameProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const wasOpenRef = useRef(false);
  const { prefs, update: updatePrefs } = useAccessibilityPrefs();

  // Text-size is applied at the widget root so it cascades to the panel and any
  // forms via the shared --cadre-font-scale token.
  const rootStyle = { "--cadre-font-scale": FONT_SCALE_VALUE[prefs.fontScale] } as CSSProperties;

  /** Report the current widget footprint height to the host. */
  const report = useCallback((type: string) => {
    const height = rootRef.current?.getBoundingClientRect().height ?? 0;
    postToHost(type, { height });
  }, []);

  // Announce open/close transitions (with a measured height) after layout.
  useLayoutEffect(() => {
    report(open ? "widget.open" : "widget.close");
  }, [open, report]);

  // Keep the host in sync as the widget's size changes (e.g. content growth).
  useEffect(() => {
    if (typeof ResizeObserver === "undefined") return;
    const el = rootRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => report("widget.resize"));
    observer.observe(el);
    return () => observer.disconnect();
  }, [report]);

  // Move focus into the panel on open (preferring the composer input so the user can
  // type immediately); restore it to the launcher on close.
  useEffect(() => {
    if (open) {
      const target = initialFocusRef?.current as (HTMLElement & { disabled?: boolean }) | null;
      if (target && !target.disabled) {
        target.focus();
      } else {
        panelRef.current?.focus();
      }
    } else if (wasOpenRef.current) {
      launcherRef.current?.focus();
    }
    wasOpenRef.current = open;
  }, [open, initialFocusRef]);

  const handlePanelKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;

    const panel = panelRef.current;
    if (!panel) return;

    const focusables = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
    if (focusables.length === 0) {
      // Nothing focusable inside yet — keep focus on the dialog container.
      event.preventDefault();
      panel.focus();
      return;
    }

    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const active = document.activeElement;

    if (active === panel) {
      // Focus is on the dialog itself: enter the content in the right direction.
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    } else if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div ref={rootRef} className="cadre-widget" style={rootStyle}>
      {open && (
        <div
          ref={panelRef}
          className="cadre-panel"
          role="dialog"
          aria-label="Cadre AI Assistant chat"
          tabIndex={-1}
          onKeyDown={handlePanelKeyDown}
        >
          <WidgetHeader
            onClose={onClose}
            onNewChat={onNewChat}
            newChatDisabled={!canStartNew}
            prefs={prefs}
            onChangePrefs={updatePrefs}
          />
          <div className="cadre-panel__content">{children}</div>
        </div>
      )}
      <Launcher ref={launcherRef} open={open} onToggle={onToggle} />
    </div>
  );
}
