// Inline error banner. Actions are supplied by the parent per state (retry a
// transient failure, reconnect/start-new after a session drop, or none for the cap
// / too-long). Dismiss always clears the banner. The error text is a polite live
// region (role="status") so screen readers announce it on appearance.

export interface ErrorAction {
  label: string;
  onClick: () => void;
}

interface ErrorBannerProps {
  error: string;
  actions?: ErrorAction[];
  onDismiss: () => void;
}

export function ErrorBanner({ error, actions = [], onDismiss }: ErrorBannerProps) {
  return (
    <div className="cadre-error-banner">
      <p className="cadre-error-text" role="status">
        {error}
      </p>
      <div className="cadre-error-actions">
        {actions.map((action) => (
          <button
            key={action.label}
            type="button"
            className="cadre-error-retry"
            onClick={action.onClick}
          >
            {action.label}
          </button>
        ))}
        <button
          type="button"
          className="cadre-error-dismiss"
          aria-label="Dismiss message"
          onClick={onDismiss}
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
