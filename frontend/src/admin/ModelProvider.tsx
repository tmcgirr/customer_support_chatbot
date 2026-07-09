import { useEffect, useState } from "react";

import type { AdminClient, AdminRole } from "./api";
import { useAdminAction } from "./useAdminAction";
import { useAdminQuery } from "./useAdminQuery";

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI (GPT)",
  anthropic: "Anthropic (Claude)",
  openrouter: "OpenRouter (Claude)",
};

function providerLabel(id: string): string {
  return PROVIDER_LABELS[id] ?? id;
}

/**
 * Switch the chat model provider at runtime (admin only, reason required, audited).
 * The set of choices is whatever is key-configured on the server — you can't select a
 * provider whose credentials aren't set. Read-only for viewers.
 */
export default function ModelProvider({
  client,
  role,
  onAuthError,
}: {
  client: AdminClient;
  role: AdminRole;
  onAuthError: () => void;
}) {
  const isAdmin = role === "admin";
  const [reloadNonce, setReloadNonce] = useState(0);
  const [selected, setSelected] = useState<string>("");
  const { error: actionError, busy, run, dialog } = useAdminAction(onAuthError);

  const { data, loading, error } = useAdminQuery(
    () => client.getModelProvider(),
    onAuthError,
    [reloadNonce],
  );

  // Sync the dropdown to the active provider whenever fresh data arrives.
  useEffect(() => {
    if (data) setSelected(data.active);
  }, [data]);

  function handleApply() {
    run({
      title: "Switch model provider",
      message: `Switch the chat model provider to ${providerLabel(selected)}? It takes effect within seconds across the app and the worker.`,
      defaultReason: "Switched model provider via admin console",
      confirmLabel: "Switch provider",
      action: (reason) => client.setModelProvider(selected, reason),
      onSuccess: () => setReloadNonce((n) => n + 1),
    });
  }

  return (
    <div className="admin-card">
      {dialog}
      <div className="admin-section-head">
        <h3 className="admin-section-title">Chat model provider</h3>
        {data && (
          <span className="admin-badge admin-badge-good">
            Active: {providerLabel(data.active)}
          </span>
        )}
      </div>
      <p className="admin-section-sub">
        Which provider answers chat turns. A switch takes effect within seconds across the app
        and the worker. Run the golden set against the target provider before switching in
        production — an approved model config is a promotion, not an ad-hoc edit.
      </p>

      {actionError && <p className="admin-error">{actionError}</p>}
      {loading && <p className="admin-muted">Loading…</p>}
      {error && <p className="admin-error">{error}</p>}

      {data && (
        <>
          <div className="admin-filters">
            <label>
              Provider{" "}
              <select
                value={selected}
                disabled={!isAdmin || busy}
                onChange={(e) => setSelected(e.target.value)}
              >
                {data.available.map((p) => (
                  <option key={p} value={p}>
                    {providerLabel(p)}
                  </option>
                ))}
                {/* Active provider isn't currently key-configured — still show it as current. */}
                {!data.available.includes(data.active) && (
                  <option value={data.active}>{providerLabel(data.active)} (current)</option>
                )}
              </select>
            </label>
            {isAdmin && (
              <button
                type="button"
                className="admin-btn admin-btn-primary"
                disabled={busy || selected === data.active}
                onClick={handleApply}
              >
                {busy ? "Switching…" : "Apply"}
              </button>
            )}
          </div>

          <p className="admin-muted">
            Default (env): {providerLabel(data.default)} · Configured:{" "}
            {data.available.length ? data.available.map(providerLabel).join(", ") : "none"}
          </p>
          {!isAdmin && (
            <p className="admin-muted">Switching the provider requires the admin role.</p>
          )}
        </>
      )}
    </div>
  );
}
