// Message input. Disabled while a response is streaming (busy lockout). Enter sends,
// Shift+Enter inserts a newline. Trimmed-empty input never sends.

import { useState } from "react";
import type { FormEvent, KeyboardEvent, RefObject } from "react";

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
        ref={inputRef}
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
