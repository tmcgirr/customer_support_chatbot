import { useState } from "react";

import type { AdminClient } from "./api";
import { useAdminQuery } from "./useAdminQuery";

const TYPE_OPTIONS = ["strategy_call", "portal_support", "human_escalation"];
const STATUS_OPTIONS = ["received", "delivering", "delivered", "delivery_failed"];

export default function Requests({
  client,
  onAuthError,
}: {
  client: AdminClient;
  onAuthError: () => void;
}) {
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");

  const { data, loading, error } = useAdminQuery(
    () =>
      client.listRequests({
        type: type || undefined,
        status: status || undefined,
      }),
    onAuthError,
    [type, status],
  );

  return (
    <div>
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

      {loading && <p className="admin-muted">Loading requests…</p>}
      {error && <p className="admin-error">{error}</p>}
      {data && (
        <table className="admin-table">
          <thead>
            <tr>
              <th>Reference</th>
              <th>Type</th>
              <th>Status</th>
              <th>Contact email</th>
              <th>Company</th>
              <th>Created</th>
              <th>Conversation ID</th>
            </tr>
          </thead>
          <tbody>
            {data.requests.length === 0 ? (
              <tr>
                <td colSpan={7} className="admin-muted">
                  No requests.
                </td>
              </tr>
            ) : (
              data.requests.map((r) => (
                <tr key={r.request_id}>
                  <td>{r.reference}</td>
                  <td>{r.type}</td>
                  <td>{r.status}</td>
                  <td>{r.contact_email}</td>
                  <td>{r.contact_company ?? "—"}</td>
                  <td>{r.created_at}</td>
                  <td>{r.conversation_id}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
