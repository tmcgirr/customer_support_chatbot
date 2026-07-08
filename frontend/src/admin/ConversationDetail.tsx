import type { AdminClient } from "./api";
import { useAdminQuery } from "./useAdminQuery";

export default function ConversationDetail({
  id,
  client,
  onAuthError,
}: {
  id: string;
  client: AdminClient;
  onAuthError: () => void;
}) {
  const { data, loading, error } = useAdminQuery(
    () => client.getConversation(id),
    onAuthError,
    [id],
  );

  if (loading) return <p className="admin-muted">Loading transcript…</p>;
  if (error) return <p className="admin-error">{error}</p>;
  if (!data) return null;

  return (
    <div>
      <h2>Conversation {data.conversation_id}</h2>
      <p className="admin-muted">
        Status: {data.status} · Outcome: {data.outcome ?? "—"} · Started: {data.started_at}
      </p>

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
          {data.messages.length === 0 ? (
            <tr>
              <td colSpan={4} className="admin-muted">
                No messages.
              </td>
            </tr>
          ) : (
            data.messages.map((m) => (
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
  );
}
