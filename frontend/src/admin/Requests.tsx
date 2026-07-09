import { Fragment, useState } from "react";

import type { AdminClient, AdminRequest, AdminRole, RevealedRequest } from "./api";
import { SortHeader, useSort } from "./tableControls";
import { useAdminAction } from "./useAdminAction";
import { useAdminQuery } from "./useAdminQuery";

const TYPE_OPTIONS = ["strategy_call", "portal_support", "human_escalation"];
const STATUS_OPTIONS = ["received", "delivering", "delivered", "delivery_failed"];

const SORT: Record<string, (r: AdminRequest) => string | number | null | undefined> = {
  type: (r) => r.type,
  status: (r) => r.status,
  created_at: (r) => r.created_at,
};

function formatField(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function Requests({
  client,
  role,
  onAuthError,
}: {
  client: AdminClient;
  role: AdminRole;
  onAuthError: () => void;
}) {
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  // Bump to re-fetch after a successful redeliver.
  const [reloadNonce, setReloadNonce] = useState(0);
  // Unmasked contact/fields keyed by request_id, shown inline on demand.
  const [revealed, setRevealed] = useState<Record<string, RevealedRequest>>({});

  const isAdmin = role === "admin";
  const { error: actionError, busy, run, dialog } = useAdminAction(onAuthError);

  const { data, loading, error } = useAdminQuery(
    () =>
      client.listRequests({
        type: type || undefined,
        status: status || undefined,
      }),
    onAuthError,
    [type, status, reloadNonce],
  );

  function handleReveal(id: string) {
    run({
      title: "Reveal contact details",
      message: "Reveal this request's unmasked contact details?",
      defaultReason: "Revealed contact details via admin console",
      confirmLabel: "Reveal",
      action: (reason) => client.revealRequest(id, reason),
      onSuccess: (result) => setRevealed((prev) => ({ ...prev, [id]: result })),
    });
  }

  function handleRedeliver(id: string) {
    run({
      title: "Redeliver request",
      message: "Re-attempt delivery of this request to its destination?",
      defaultReason: "Redelivered via admin console",
      confirmLabel: "Redeliver",
      action: (reason) => client.redeliver(id, reason),
      onSuccess: () => setReloadNonce((n) => n + 1),
    });
  }

  const { sorted, sort, toggle } = useSort(data?.requests ?? [], SORT, {
    key: "created_at",
    dir: "desc",
  });
  const colCount = isAdmin ? 12 : 11;

  return (
    <div>
      {dialog}
      <div className="admin-filters">
        <label>
          Type{" "}
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All</option>
            {TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status{" "}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>

      {actionError && <p className="admin-error">{actionError}</p>}
      {loading && <p className="admin-muted">Loading requests…</p>}
      {error && <p className="admin-error">{error}</p>}
      {data && (
        <div className="admin-tablewrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Reference</th>
              <SortHeader label="Type" sortKey="type" sort={sort} onToggle={toggle} />
              <SortHeader label="Status" sortKey="status" sort={sort} onToggle={toggle} />
              <th>Contact email</th>
              <th>Company</th>
              <th>Destination</th>
              <th>Channel</th>
              <th>External ref</th>
              <th>Last delivery error</th>
              <SortHeader label="Created" sortKey="created_at" sort={sort} onToggle={toggle} />
              <th>Conversation ID</th>
              {isAdmin && <th className="admin-col-sticky">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={colCount} className="admin-muted">
                  No requests.
                </td>
              </tr>
            ) : (
              sorted.map((r) => {
                const unmasked = revealed[r.request_id];
                return (
                  <Fragment key={r.request_id}>
                    <tr>
                      <td>{r.reference}</td>
                      <td>{r.type}</td>
                      <td>{r.status}</td>
                      <td>{unmasked ? unmasked.contact.email : r.contact_email}</td>
                      <td>{unmasked?.contact.company ?? r.contact_company ?? "—"}</td>
                      <td>{r.destination ?? "—"}</td>
                      <td>{r.delivery_channel ?? "—"}</td>
                      <td>{r.external_reference ?? "—"}</td>
                      <td className="admin-content">{r.last_delivery_error ?? "—"}</td>
                      <td>{r.created_at}</td>
                      <td>{r.conversation_id}</td>
                      {isAdmin && (
                        <td className="admin-col-sticky">
                          <button
                            type="button"
                            className="admin-link"
                            disabled={busy}
                            onClick={() => handleReveal(r.request_id)}
                          >
                            Reveal
                          </button>
                          {r.status === "delivery_failed" && (
                            <button
                              type="button"
                              className="admin-link"
                              disabled={busy}
                              onClick={() => handleRedeliver(r.request_id)}
                            >
                              Redeliver
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                    {unmasked && (
                      <tr className="admin-reveal-row">
                        <td colSpan={colCount}>
                          <div className="admin-reveal">
                            <strong>Unmasked contact:</strong>{" "}
                            {unmasked.contact.name ?? "—"} · {unmasked.contact.email} ·{" "}
                            {unmasked.contact.company ?? "—"}
                            {Object.keys(unmasked.fields).length > 0 && (
                              <ul className="admin-reveal-fields">
                                {Object.entries(unmasked.fields).map(([key, value]) => (
                                  <li key={key}>
                                    <span className="admin-muted">{key}:</span>{" "}
                                    {formatField(value)}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      )}
    </div>
  );
}
