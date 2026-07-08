// Inline error banner. Retry is optional — the parent omits it for non-retryable
// states (message cap, too-long). Dismiss always clears the banner. The error text
// is a polite live region (role="status") so screen readers announce it on appearance.

interface ErrorBannerProps {
  error: string;
  onRetry?: () => void;
  onDismiss: () => void;
}

export function ErrorBanner({ error, onRetry, onDismiss }: ErrorBannerProps) {
  return (
    <div className="cadre-error-banner">
      <p className="cadre-error-text" role="status">
        {error}
      </p>
      <div className="cadre-error-actions">
        {onRetry && (
          <button type="button" className="cadre-error-retry" onClick={onRetry}>
            Retry
          </button>
        )}
        <button
          type="button"
          className="cadre-error-dismiss"
          aria-label="Dismiss error"
          onClick={onDismiss}
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
