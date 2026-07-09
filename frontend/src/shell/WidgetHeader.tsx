export interface WidgetHeaderProps {
  /** Close the chat panel. */
  onClose: () => void;
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true" focusable="false">
      <path
        d="M6 6l12 12M18 6L6 18"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** Small "sparkle" glyph for the assistant avatar (decorative). */
function SparkIcon() {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="currentColor" aria-hidden="true" focusable="false">
      <path d="M12 2.5l1.8 4.9 4.9 1.8-4.9 1.8L12 15.9l-1.8-4.9L5.3 9.2l4.9-1.8L12 2.5Z" />
      <path d="M18.5 14.5l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9.9-2.4Z" opacity="0.85" />
    </svg>
  );
}

/** Panel header: an assistant avatar, product name, an "AI" badge, and close. */
export function WidgetHeader({ onClose }: WidgetHeaderProps) {
  return (
    <header className="cadre-header">
      <div className="cadre-header__title">
        <span className="cadre-header__avatar" aria-hidden="true">
          <SparkIcon />
        </span>
        <span className="cadre-header__name">Cadre AI Assistant</span>
        <span className="cadre-header__badge" title="Powered by AI">
          AI
        </span>
      </div>
      <button
        type="button"
        className="cadre-header__close"
        aria-label="Close chat"
        onClick={onClose}
      >
        <CloseIcon />
      </button>
    </header>
  );
}
