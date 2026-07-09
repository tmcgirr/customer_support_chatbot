// Message input. Disabled while a response is streaming (busy lockout). Enter sends,
// Shift+Enter inserts a newline. Trimmed-empty input never sends. The textarea
// auto-grows with its content up to MAX_ROWS lines, then caps and scrolls.

import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent, MutableRefObject, RefObject } from "react";

// Grow the input up to this many text rows before capping the height and letting
// it scroll internally. Height is derived from the live line-height/padding so it
// tracks the CSS rather than a hard-coded pixel value.
const MAX_ROWS = 4;

interface ComposerProps {
  onSend: (content: string) => void;
  disabled?: boolean;
  placeholder?: string;
  /** Optional ref to the textarea so the shell can move focus here on panel open. */
  inputRef?: RefObject<HTMLTextAreaElement>;
}

/** Upward arrow send glyph (decorative; the button carries the accessible name). */
function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true" focusable="false">
      <path
        d="M12 19V5M12 5l-6 6M12 5l6 6"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function Composer({ onSend, disabled, placeholder, inputRef }: ComposerProps) {
  const [value, setValue] = useState("");
  // Own the DOM node locally (for measuring) while still forwarding it to the
  // optional caller-provided ref used for focus-on-open.
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const setRefs = useCallback(
    (node: HTMLTextAreaElement | null) => {
      textareaRef.current = node;
      if (inputRef) {
        (inputRef as MutableRefObject<HTMLTextAreaElement | null>).current = node;
      }
    },
    [inputRef],
  );

  // Reset to the natural height, then grow to fit content up to the row cap. Past
  // the cap the height holds and the textarea scrolls.
  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const styles = window.getComputedStyle(el);
    const lineHeight = parseFloat(styles.lineHeight) || 21;
    const padding = (parseFloat(styles.paddingTop) || 0) + (parseFloat(styles.paddingBottom) || 0);
    const maxHeight = lineHeight * MAX_ROWS + padding;
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
    el.style.overflowY = el.scrollHeight > maxHeight ? "auto" : "hidden";
  }, []);

  // Re-fit on every value change: typing, growing, and the reset-to-one-line after
  // send. Runs on mount too, so the initial height is correct.
  useLayoutEffect(() => {
    resize();
  }, [value, resize]);

  const submit = () => {
    const trimmed = value.trim();
    if (disabled || trimmed.length === 0) return;
    onSend(trimmed);
    setValue("");
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    submit();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form className="cadre-composer" onSubmit={handleSubmit}>
      <textarea
        ref={setRefs}
        id="cadre-composer-input"
        className="cadre-composer-input"
        aria-label="Message"
        rows={1}
        value={value}
        disabled={disabled}
        placeholder={placeholder ?? "Type your message"}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={handleKeyDown}
      />
      <button
        type="submit"
        className="cadre-composer-send"
        aria-label="Send message"
        disabled={disabled || value.trim().length === 0}
      >
        <SendIcon />
      </button>
    </form>
  );
}
