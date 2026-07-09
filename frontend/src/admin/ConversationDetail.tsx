import { useState } from "react";

import type { AdminClient, AdminRole, RevealedConversation } from "./api";
import { useAdminAction } from "./useAdminAction";
import { useAdminQuery } from "./useAdminQuery";

export default function ConversationDetail({
  id,
  client,
  role,
  onAuthError,
}: {
  id: string;
  client: AdminClient;
  role: AdminRole;
  onAuthError: () => void;
}) {
  const [revealed, setRevealed] = useState<RevealedConversation | null>(null);
  const isAdmin = role === "admin";
  const { error: actionError, busy, run, dialog } = useAdminAction(onAuthError);

  const { data, loading, error } = useAdminQuery(
    () => client.getConversation(id),
    onAuthError,
    [id],
  );

  if (loading) return <p className="admin-muted">Loading transcript…</p>;
  if (error) return <p className="admin-error">{error}</p>;
  if (!data) return null;

  function handleReveal() {
    run({
      title: "Reveal PII",
      message:
        "Unmask the personal information (names, emails, phone numbers) in this transcript? This is recorded in the audit log.",
      defaultReason: "Revealed transcript PII via admin console",
      confirmLabel: "Reveal PII",
      action: (reason) => client.revealConversation(id, reason),
      onSuccess: (result) => setRevealed(result),
    });
  }

  // Normalize revealed messages to the same display shape (they carry no status).
  const rows = revealed
    ? revealed.messages.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        status: "—",
        created_at: m.created_at,
      }))
    : data.messages;

  return (
    <div>
      {dialog}
      <h2>Conversation {data.conversation_id}</h2>
      <p className="admin-muted">
        Status: {data.status} · Outcome: {data.outcome ?? "—"} · Started: {data.started_at}
      </p>

      {data.summary && (
        <div className="admin-card">
          <h3>Summary</h3>
          <p className="admin-content">{data.summary}</p>
          {data.key_points.length > 0 && (
            <ul className="admin-reveal-fields">
              {data.key_points.map((point, i) => (
                <li key={i}>{point}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {isAdmin && !revealed && (
        <p className="admin-reveal-line">
          <button
            type="button"
            className="admin-btn admin-btn-ghost admin-btn-sm"
            disabled={busy}
            onClick={handleReveal}
          >
            Reveal PII
          </button>
          <span className="admin-muted">
            Personal details (names, emails, phone numbers) are masked below; revealing is audited.
          </span>
        </p>
      )}
      {revealed && <p className="admin-muted">PII revealed — showing the unmasked transcript.</p>}
      {actionError && <p className="admin-error">{actionError}</p>}

      <div className="admin-tablewrap">
        <table className="admin-table">
        <thead>
          <tr>
            <th>Role</th>
            <th>Content</th>
            <th>Status</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={4} className="admin-muted">
                No messages.
              </td>
            </tr>
          ) : (
            rows.map((m) => (
              <tr key={m.id}>
                <td>{m.role}</td>
                <td className="admin-content">{m.content}</td>
                <td>{m.status}</td>
                <td>{m.created_at}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
      </div>
    </div>
  );
}
