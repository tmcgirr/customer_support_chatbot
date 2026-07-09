import { useState } from "react";

import type { AdminClient, AdminRole } from "./api";
import ConversationDetail from "./ConversationDetail";
import { useAdminQuery } from "./useAdminQuery";

export default function Conversations({
  client,
  role,
  onAuthError,
}: {
  client: AdminClient;
  role: AdminRole;
  onAuthError: () => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { data, loading, error } = useAdminQuery(
    () => client.listConversations(),
    onAuthError,
    [],
  );

  if (selectedId) {
    return (
      <div>
        <button type="button" className="admin-link" onClick={() => setSelectedId(null)}>
          ← Back to conversations
        </button>
        <ConversationDetail
          id={selectedId}
          client={client}
          role={role}
          onAuthError={onAuthError}
        />
      </div>
    );
  }

  if (loading) return <p className="admin-muted">Loading conversations…</p>;
  if (error) return <p className="admin-error">{error}</p>;
  if (!data) return null;

  return (
    <table className="admin-table">
      <thead>
        <tr>
          <th>Conversation ID</th>
          <th>Summary</th>
          <th>Status</th>
          <th>Outcome</th>
          <th className="admin-num">Messages</th>
          <th>Last activity</th>
        </tr>
      </thead>
      <tbody>
        {data.conversations.length === 0 ? (
          <tr>
            <td colSpan={6} className="admin-muted">
              No conversations.
            </td>
          </tr>
        ) : (
          data.conversations.map((c) => (
            <tr
              key={c.conversation_id}
              className="admin-row-clickable"
              onClick={() => setSelectedId(c.conversation_id)}
            >
              <td>{c.conversation_id}</td>
              <td className="admin-content">{c.summary ?? <span className="admin-muted">—</span>}</td>
              <td>{c.status}</td>
              <td>{c.outcome ?? "—"}</td>
              <td className="admin-num">{c.message_count}</td>
              <td>{c.last_activity_at}</td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
