import { useState } from "react";

import type { AdminClient, AdminRole, PrivacyRequest } from "./api";
import { distinct, FilterSelect, SortHeader, useSort } from "./tableControls";
import { useAdminAction } from "./useAdminAction";
import { useAdminQuery } from "./useAdminQuery";

/** Summarize per-store result counts, e.g. "3 conversations, 2 requests, 1 feedback". */
function summarizeCounts(counts: Record<string, number> | null): string {
  if (!counts) return "—";
  const parts = Object.entries(counts).map(([key, value]) => `${value} ${key}`);
  return parts.length > 0 ? parts.join(", ") : "—";
}

const SORT: Record<string, (r: PrivacyRequest) => string | number | null | undefined> = {
  type: (r) => r.type,
  verification_status: (r) => r.verification_status,
  status: (r) => r.status,
  created_at: (r) => r.created_at,
};

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
  const [type, setType] = useState("");
  const [verification, setVerification] = useState("");
  const [status, setStatus] = useState("");
  const isAdmin = role === "admin";
  const { error: actionError, busy, run, dialog } = useAdminAction(onAuthError);

  const { data, loading, error } = useAdminQuery(() => client.listPrivacyRequests(), onAuthError, [
    reloadNonce,
  ]);

  function handleVerify(id: string) {
    run({
      title: "Verify privacy request",
      message: "Verify this request? Verifying a deletion enqueues erasure — this cannot be undone.",
      defaultReason: "Verified via admin console",
      confirmLabel: "Verify",
      action: (reason) => client.verifyPrivacyRequest(id, reason),
      onSuccess: () => setReloadNonce((n) => n + 1),
    });
  }

  const all = data?.requests ?? [];
  const filtered = all.filter(
    (r) =>
      (!type || r.type === type) &&
      (!verification || r.verification_status === verification) &&
      (!status || r.status === status),
  );
  const { sorted, sort, toggle } = useSort(filtered, SORT, { key: "created_at", dir: "desc" });
  const colCount = isAdmin ? 8 : 7;

  return (
    <div>
      {dialog}
      {actionError && <p className="admin-error">{actionError}</p>}
      {loading && <p className="admin-muted">Loading privacy requests…</p>}
      {error && <p className="admin-error">{error}</p>}
      {data && (
        <>
          <div className="admin-filters">
            <FilterSelect
              label="Type"
              value={type}
              options={distinct(all, (r) => r.type)}
              onChange={setType}
            />
            <FilterSelect
              label="Verification"
              value={verification}
              options={distinct(all, (r) => r.verification_status)}
              onChange={setVerification}
            />
            <FilterSelect
              label="Status"
              value={status}
              options={distinct(all, (r) => r.status)}
              onChange={setStatus}
            />
            <span className="admin-muted">
              {sorted.length} of {all.length}
            </span>
          </div>

          <div className="admin-tablewrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <SortHeader label="Type" sortKey="type" sort={sort} onToggle={toggle} />
                  <th>Requester email</th>
                  <th>Conversation ID</th>
                  <SortHeader
                    label="Verification"
                    sortKey="verification_status"
                    sort={sort}
                    onToggle={toggle}
                  />
                  <SortHeader label="Status" sortKey="status" sort={sort} onToggle={toggle} />
                  <th>Result counts</th>
                  <SortHeader
                    label="Created"
                    sortKey="created_at"
                    sort={sort}
                    onToggle={toggle}
                  />
                  {isAdmin && <th className="admin-col-sticky">Actions</th>}
                </tr>
              </thead>
              <tbody>
                {sorted.length === 0 ? (
                  <tr>
                    <td colSpan={colCount} className="admin-muted">
                      No privacy requests.
                    </td>
                  </tr>
                ) : (
                  sorted.map((r) => (
                    <tr key={r.request_id}>
                      <td>{r.type}</td>
                      <td>{r.requester_email}</td>
                      <td>{r.conversation_id ?? "—"}</td>
                      <td>{r.verification_status}</td>
                      <td>{r.status}</td>
                      <td>{summarizeCounts(r.result_counts)}</td>
                      <td>{r.created_at}</td>
                      {isAdmin && (
                        <td className="admin-col-sticky">
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
          </div>
        </>
      )}
    </div>
  );
}
