import { useEffect, useState } from "react";

/**
 * Confirmation modal for a privileged admin action. The reason is OPTIONAL (a
 * default is recorded when left blank — see docs/DECISIONS_LOG.md 2026-07-09), so
 * an admin can one-click Confirm; a typed note is still written to the audit log.
 * Replaces the old native window.prompt().
 */
export default function ReasonDialog({
  title,
  message,
  confirmLabel = "Confirm",
  danger,
  busy,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  busy: boolean;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onCancel();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  return (
    <div className="admin-modal-overlay" role="presentation" onClick={() => !busy && onCancel()}>
      <div
        className="admin-modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="admin-modal-title">{title}</h3>
        <p className="admin-modal-message">{message}</p>
        <label className="admin-modal-field">
          <span>Reason (optional — recorded in the audit log)</span>
          <textarea
            aria-label="Reason"
            rows={3}
            value={reason}
            placeholder="Add a note, or leave blank"
            autoFocus
            disabled={busy}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        <div className="admin-modal-actions">
          <button
            type="button"
            className="admin-btn admin-btn-ghost"
            disabled={busy}
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            className={`admin-btn ${danger ? "admin-btn-danger" : "admin-btn-primary"}`}
            disabled={busy}
            onClick={() => onConfirm(reason.trim())}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
