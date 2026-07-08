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

/** Panel header: product name, an "AI" badge, and a close button. */
export function WidgetHeader({ onClose }: WidgetHeaderProps) {
  return (
    <header className="cadre-header">
      <div className="cadre-header__title">
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
