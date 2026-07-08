import { useState } from "react";

import { AdminForbiddenError } from "./api";

/**
 * Shared driver for privileged admin actions (reveal / redeliver / approve).
 * Prompts for an audit reason, runs the action, and surfaces a typed error:
 * a 403 (AdminForbiddenError) becomes an inline "requires admin role" message
 * rather than crashing or dropping back to the login screen.
 */
export function useAdminAction() {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run<T>(
    promptMessage: string,
    action: (reason: string) => Promise<T>,
    onSuccess?: (result: T) => void,
  ): Promise<void> {
    const reason = window.prompt(promptMessage);
    if (reason === null) return; // user cancelled
    setBusy(true);
    setError(null);
    try {
      const result = await action(reason);
      onSuccess?.(result);
    } catch (err: unknown) {
      if (err instanceof AdminForbiddenError) {
        setError("This action requires an admin role.");
      } else {
        setError(err instanceof Error ? err.message : "Action failed.");
      }
    } finally {
      setBusy(false);
    }
  }

  return { error, busy, run };
}
