import { useState } from "react";

import type { AdminClient, AdminRole } from "./api";
import { useAdminAction } from "./useAdminAction";
import { useAdminQuery } from "./useAdminQuery";

export default function Knowledge({
  client,
  role,
  onAuthError,
}: {
  client: AdminClient;
  role: AdminRole;
  onAuthError: () => void;
}) {
  // Bump to re-fetch after a successful approval.
  const [reloadNonce, setReloadNonce] = useState(0);
  const isAdmin = role === "admin";
  const { error: actionError, busy, run } = useAdminAction();

  const { data, loading, error } = useAdminQuery(
    () => client.listCanonical(),
    onAuthError,
    [reloadNonce],
  );

  function handleApprove(intent: string) {
    run(
      "Reason for approving this canonical answer (audited):",
      (reason) => client.approveCanonical(intent, reason),
      () => setReloadNonce((n) => n + 1),
    );
  }

  const colCount = isAdmin ? 6 : 5;

  return (
    <div>
      {actionError && <p className="admin-error">{actionError}</p>}
      {loading && <p className="admin-muted">Loading canonical answers…</p>}
      {error && <p className="admin-error">{error}</p>}
      {data && (
        <table className="admin-table">
          <thead>
            <tr>
              <th>Intent</th>
              <th>Name</th>
              <th>Status</th>
              <th>Owner</th>
              <th>Review date</th>
              {isAdmin && <th>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {data.answers.length === 0 ? (
              <tr>
                <td colSpan={colCount} className="admin-muted">
                  No canonical answers.
                </td>
              </tr>
            ) : (
              data.answers.map((a) => (
                <tr key={a.intent}>
                  <td>{a.intent}</td>
                  <td>{a.name}</td>
                  <td>{a.status}</td>
                  <td>{a.owner ?? "—"}</td>
                  <td>{a.review_date ?? "—"}</td>
                  {isAdmin && (
                    <td>
                      {a.status === "draft" && (
                        <button
                          type="button"
                          className="admin-link"
                          disabled={busy}
                          onClick={() => handleApprove(a.intent)}
                        >
                          Approve
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
