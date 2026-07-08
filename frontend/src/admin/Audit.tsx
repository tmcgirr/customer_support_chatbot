import type { AdminClient } from "./api";
import { useAdminQuery } from "./useAdminQuery";

export default function Audit({
  client,
  onAuthError,
}: {
  client: AdminClient;
  onAuthError: () => void;
}) {
  const { data, loading, error } = useAdminQuery(() => client.listAudit(), onAuthError, []);

  if (loading) return <p className="admin-muted">Loading audit log…</p>;
  if (error) return <p className="admin-error">{error}</p>;
  if (!data) return null;

  return (
    <table className="admin-table">
      <thead>
        <tr>
          <th>At</th>
          <th>Actor</th>
          <th>Role</th>
          <th>Action</th>
          <th>Target type</th>
          <th>Target ID</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        {data.entries.length === 0 ? (
          <tr>
            <td colSpan={7} className="admin-muted">
              No audit entries.
            </td>
          </tr>
        ) : (
          data.entries.map((e, i) => (
            <tr key={`${e.at}-${e.actor}-${i}`}>
              <td>{e.at}</td>
              <td>{e.actor}</td>
              <td>{e.role}</td>
              <td>{e.action}</td>
              <td>{e.target_type}</td>
              <td>{e.target_id}</td>
              <td className="admin-content">{e.reason ?? "—"}</td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
