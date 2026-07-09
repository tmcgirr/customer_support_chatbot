import { createElement, type ReactNode, useState } from "react";

import { AdminAuthError, AdminForbiddenError } from "./api";
import ReasonDialog from "./ReasonDialog";

/**
 * Shared driver for privileged admin actions (approve / reveal / redeliver / verify).
 * Opens a confirmation modal (ReasonDialog) with an OPTIONAL reason, runs the action
 * on Confirm, and surfaces a typed error: a 403 (AdminForbiddenError) becomes an inline
 * "requires admin role" message; a 401 (AdminAuthError) routes to `onAuthError` so a
 * session invalidated mid-action drops back to login (matching useAdminQuery).
 *
 * The action always receives a non-empty reason: the typed note, or the caller's
 * `defaultReason` when left blank (still written to the append-only audit log).
 */
export interface RunOptions<T> {
  title: string;
  message: string;
  defaultReason: string;
  confirmLabel?: string;
  danger?: boolean;
  action: (reason: string) => Promise<T>;
  onSuccess?: (result: T) => void;
}

interface Pending {
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  defaultReason: string;
  action: (reason: string) => Promise<unknown>;
  onSuccess?: (result: unknown) => void;
}

export function useAdminAction(onAuthError?: () => void) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);

  function run<T>(options: RunOptions<T>): void {
    setError(null);
    setPending(options as Pending);
  }

  async function confirm(reason: string): Promise<void> {
    if (!pending) return;
    const { action, onSuccess, defaultReason } = pending;
    setBusy(true);
    setError(null);
    try {
      const result = await action(reason || defaultReason);
      onSuccess?.(result);
      setPending(null);
    } catch (err: unknown) {
      setPending(null);
      if (err instanceof AdminAuthError) {
        onAuthError?.(); // session died mid-action → back to login
      } else if (err instanceof AdminForbiddenError) {
        setError("This action requires an admin role.");
      } else {
        setError(err instanceof Error ? err.message : "Action failed.");
      }
    } finally {
      setBusy(false);
    }
  }

  const dialog: ReactNode = pending
    ? createElement(ReasonDialog, {
        title: pending.title,
        message: pending.message,
        confirmLabel: pending.confirmLabel,
        danger: pending.danger,
        busy,
        onConfirm: confirm,
        onCancel: () => setPending(null),
      })
    : null;

  return { error, busy, run, dialog };
}
