import { useState } from "react";

import type { AdminClient, AdminRole } from "./api";
import { useAdminAction } from "./useAdminAction";
import { useAdminQuery } from "./useAdminQuery";

/** Summarize per-store result counts, e.g. "3 conversations, 2 requests, 1 feedback". */
function summarizeCounts(counts: Record<string, number> | null): string {
  if (!counts) return "—";
  const parts = Object.entries(counts).map(([key, value]) => `${value} ${key}`);
  return parts.length > 0 ? parts.join(", ") : "—";
}

export default function Privacy({
  client,
  role,
  onAuthError,
}: {
  client: AdminClient;
  role: AdminRole;
  onAuthError: () => void;
}) {
  // Bump to re-fetch after a successful verification.
  const [reloadNonce, setReloadNonce] = useState(0);
  const isAdmin = role === "admin";
  const { error: actionError, busy, run } = useAdminAction();

  const { data, loading, error } = useAdminQuery(
    () => client.listPrivacyRequests(),
    onAuthError,
    [reloadNonce],
  );

  function handleVerify(id: string) {
    run(
      "Reason for verifying this privacy request (audited). Verifying a deletion enqueues erasure:",
      (reason) => client.verifyPrivacyRequest(id, reason),
      () => setReloadNonce((n) => n + 1),
    );
  }

  const colCount = isAdmin ? 8 : 7;

  return (
    <div>
      {actionError && <p className="admin-error">{actionError}</p>}
      {loading && <p className="admin-muted">Loading privacy requests…</p>}
      {error && <p className="admin-error">{error}</p>}
      {data && (
        <table className="admin-table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Requester email</th>
              <th>Conversation ID</th>
              <th>Verification</th>
              <th>Status</th>
              <th>Result counts</th>
              <th>Created</th>
              {isAdmin && <th>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {data.requests.length === 0 ? (
              <tr>
                <td colSpan={colCount} className="admin-muted">
                  No privacy requests.
                </td>
              </tr>
            ) : (
              data.requests.map((r) => (
                <tr key={r.request_id}>
                  <td>{r.type}</td>
                  <td>{r.requester_email}</td>
                  <td>{r.conversation_id ?? "—"}</td>
                  <td>{r.verification_status}</td>
                  <td>{r.status}</td>
                  <td>{summarizeCounts(r.result_counts)}</td>
                  <td>{r.created_at}</td>
                  {isAdmin && (
                    <td>
                      {r.verification_status === "pending" && (
                        <button
                          type="button"
                          className="admin-link"
                          disabled={busy}
                          onClick={() => handleVerify(r.request_id)}
                        >
                          Verify
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
