// Message input. Disabled while a response is streaming (busy lockout). Enter sends,
// Shift+Enter inserts a newline. Trimmed-empty input never sends.

import { useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";

interface ComposerProps {
  onSend: (content: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function Composer({ onSend, disabled, placeholder }: ComposerProps) {
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
        Send
      </button>
    </form>
  );
}
