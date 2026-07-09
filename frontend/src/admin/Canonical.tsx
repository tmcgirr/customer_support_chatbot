import { useState } from "react";

import type { AdminClient, AdminRole, CanonicalAnswer } from "./api";
import { distinct, FilterSelect, SortHeader, useSort } from "./tableControls";
import { useAdminAction } from "./useAdminAction";
import { useAdminQuery } from "./useAdminQuery";

const SORT: Record<string, (a: CanonicalAnswer) => string | number | null | undefined> = {
  intent: (a) => a.intent,
  name: (a) => a.name,
  status: (a) => a.status,
  review_date: (a) => a.review_date,
};

export default function Canonical({
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
  const [status, setStatus] = useState("");
  const isAdmin = role === "admin";
  const { error: actionError, busy, run, dialog } = useAdminAction(onAuthError);

  const { data, loading, error } = useAdminQuery(() => client.listCanonical(), onAuthError, [
    reloadNonce,
  ]);

  function handleApprove(intent: string) {
    run({
      title: "Approve canonical answer",
      message: `Approve “${intent}”? Once approved, the bot serves it.`,
      defaultReason: "Approved via admin console",
      confirmLabel: "Approve",
      action: (reason) => client.approveCanonical(intent, reason),
      onSuccess: () => setReloadNonce((n) => n + 1),
    });
  }

  const all = data?.answers ?? [];
  const filtered = all.filter((a) => !status || a.status === status);
  // Default: drafts (awaiting approval) before approved.
  const { sorted, sort, toggle } = useSort(filtered, SORT, { key: "status", dir: "desc" });
  const colCount = isAdmin ? 6 : 5;

  return (
    <div>
      {dialog}
      {actionError && <p className="admin-error">{actionError}</p>}
      {loading && <p className="admin-muted">Loading canonical answers…</p>}
      {error && <p className="admin-error">{error}</p>}
      {data && (
        <>
          <div className="admin-filters">
            <FilterSelect
              label="Status"
              value={status}
              options={distinct(all, (a) => a.status)}
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
                  <SortHeader label="Intent" sortKey="intent" sort={sort} onToggle={toggle} />
                  <SortHeader label="Name" sortKey="name" sort={sort} onToggle={toggle} />
                  <SortHeader label="Status" sortKey="status" sort={sort} onToggle={toggle} />
                  <th>Owner</th>
                  <SortHeader
                    label="Review date"
                    sortKey="review_date"
                    sort={sort}
                    onToggle={toggle}
                  />
                  {isAdmin && <th>Actions</th>}
                </tr>
              </thead>
              <tbody>
                {sorted.length === 0 ? (
                  <tr>
                    <td colSpan={colCount} className="admin-muted">
                      No canonical answers.
                    </td>
                  </tr>
                ) : (
                  sorted.map((a) => (
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
          </div>
        </>
      )}
    </div>
  );
}
