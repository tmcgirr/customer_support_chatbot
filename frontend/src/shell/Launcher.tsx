import { forwardRef } from "react";

export interface LauncherProps {
  /** Whether the chat panel is currently open. */
  open: boolean;
  /** Toggle the panel open/closed. */
  onToggle: () => void;
}

function ChatIcon() {
  return (
    <svg viewBox="0 0 24 24" width="26" height="26" fill="none" aria-hidden="true" focusable="false">
      <path
        d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v7A2.5 2.5 0 0 1 17.5 15H10l-4.2 3.5A1 1 0 0 1 4 17.7V5.5Z"
        fill="currentColor"
      />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" width="24" height="24" fill="none" aria-hidden="true" focusable="false">
      <path
        d="M6 6l12 12M18 6L6 18"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * Floating round launcher button (bottom-right). Real <button> so it is keyboard
 * operable; `aria-expanded` reflects the panel state.
 */
export const Launcher = forwardRef<HTMLButtonElement, LauncherProps>(function Launcher(
  { open, onToggle },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      className={`cadre-launcher${open ? " is-open" : ""}`}
      aria-expanded={open}
      aria-haspopup="dialog"
      aria-label={open ? "Close chat" : "Chat with us"}
      onClick={onToggle}
    >
      <span className="cadre-launcher__icon">{open ? <CloseIcon /> : <ChatIcon />}</span>
    </button>
  );
});
