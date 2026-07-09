import type { AdminClient } from "./api";
import { useAdminQuery } from "./useAdminQuery";

function BreakdownTable({
  title,
  rows,
  sorted = false,
}: {
  title: string;
  rows: Record<string, number>;
  sorted?: boolean;
}) {
  // `rows ?? {}` guards against a version-skewed backend that omits a newer field
  // (an undefined here would throw in render and white-screen the whole console).
  const entries = sorted
    ? Object.entries(rows ?? {})
        .filter(([key]) => key !== "unset") // hide the not-yet-labeled placeholder from ranked cards
        .sort((a, b) => b[1] - a[1]) // highest count first (top topics)
    : Object.entries(rows ?? {});
  return (
    <div className="admin-card">
      <h3>{title}</h3>
      {entries.length === 0 ? (
        <p className="admin-muted">None.</p>
      ) : (
        <table>
          <tbody>
            {entries.map(([key, value]) => (
              <tr key={key}>
                <td>{key}</td>
                <td className="admin-num">{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function Dashboard({
  client,
  onAuthError,
}: {
  client: AdminClient;
  onAuthError: () => void;
}) {
  const { data, loading, error } = useAdminQuery(() => client.getDashboard(), onAuthError, []);

  if (loading) return <p className="admin-muted">Loading dashboard…</p>;
  if (error) return <p className="admin-error">{error}</p>;
  if (!data) return null;

  return (
    <div>
      <div className="admin-stats">
        <div className="admin-stat">
          <span className="admin-stat-label">Conversations</span>
          <span className="admin-stat-value">{data.conversations.total}</span>
        </div>
        <div className="admin-stat">
          <span className="admin-stat-label">Requests</span>
          <span className="admin-stat-value">{data.requests.total}</span>
        </div>
        <div className="admin-stat">
          <span className="admin-stat-label">Unresolved questions</span>
          <span className="admin-stat-value">{data.unresolved_questions}</span>
        </div>
      </div>

      <div className="admin-card-grid">
        <BreakdownTable title="Conversations by status" rows={data.conversations.by_status} />
        <BreakdownTable title="Conversations by outcome" rows={data.conversations.by_outcome} />
        <BreakdownTable title="Top topics" rows={data.conversations.by_topic} sorted />
        <BreakdownTable title="Visitor intent" rows={data.conversations.by_intent} sorted />
        <BreakdownTable title="Requests by type" rows={data.requests.by_type} />
        <BreakdownTable title="Requests by status" rows={data.requests.by_status} />
      </div>
    </div>
  );
}
