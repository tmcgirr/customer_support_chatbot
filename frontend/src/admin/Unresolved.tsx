import type { AdminClient } from "./api";
import { useAdminQuery } from "./useAdminQuery";

export default function Unresolved({
  client,
  onAuthError,
}: {
  client: AdminClient;
  onAuthError: () => void;
}) {
  const { data, loading, error } = useAdminQuery(() => client.listUnresolved(), onAuthError, []);

  if (loading) return <p className="admin-muted">Loading unresolved questions…</p>;
  if (error) return <p className="admin-error">{error}</p>;
  if (!data) return null;

  return (
    <table className="admin-table">
      <thead>
        <tr>
          <th>Question</th>
          <th>At</th>
          <th>Conversation ID</th>
        </tr>
      </thead>
      <tbody>
        {data.questions.length === 0 ? (
          <tr>
            <td colSpan={3} className="admin-muted">
              No unresolved questions.
            </td>
          </tr>
        ) : (
          data.questions.map((q, i) => (
            <tr key={`${q.conversation_id}-${i}`}>
              <td className="admin-content">{q.question}</td>
              <td>{q.at}</td>
              <td>{q.conversation_id}</td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
