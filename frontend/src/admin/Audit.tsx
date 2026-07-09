import { useState } from "react";

import type { AdminClient, AuditEntry } from "./api";
import { distinct, FilterSelect, SortHeader, useSort } from "./tableControls";
import { useAdminQuery } from "./useAdminQuery";

const SORT: Record<string, (e: AuditEntry) => string | number | null | undefined> = {
  at: (e) => e.at,
  actor: (e) => e.actor,
  action: (e) => e.action,
  target_type: (e) => e.target_type,
};

export default function Audit({
  client,
  onAuthError,
}: {
  client: AdminClient;
  onAuthError: () => void;
}) {
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [targetType, setTargetType] = useState("");
  const { data, loading, error } = useAdminQuery(() => client.listAudit(), onAuthError, []);

  const all = data?.entries ?? [];
  const filtered = all.filter(
    (e) =>
      (!action || e.action === action) &&
      (!actor || e.actor === actor) &&
      (!targetType || e.target_type === targetType),
  );
  const { sorted, sort, toggle } = useSort(filtered, SORT, { key: "at", dir: "desc" });

  if (loading) return <p className="admin-muted">Loading audit log…</p>;
  if (error) return <p className="admin-error">{error}</p>;
  if (!data) return null;

  return (
    <div>
      <div className="admin-filters">
        <FilterSelect
          label="Action"
          value={action}
          options={distinct(all, (e) => e.action)}
          onChange={setAction}
        />
        <FilterSelect
          label="Actor"
          value={actor}
          options={distinct(all, (e) => e.actor)}
          onChange={setActor}
        />
        <FilterSelect
          label="Target"
          value={targetType}
          options={distinct(all, (e) => e.target_type)}
          onChange={setTargetType}
        />
        <span className="admin-muted">
          {sorted.length} of {all.length}
        </span>
      </div>

      <div className="admin-tablewrap">
        <table className="admin-table">
          <thead>
            <tr>
              <SortHeader label="At" sortKey="at" sort={sort} onToggle={toggle} />
              <SortHeader label="Actor" sortKey="actor" sort={sort} onToggle={toggle} />
              <th>Role</th>
              <SortHeader label="Action" sortKey="action" sort={sort} onToggle={toggle} />
              <SortHeader
                label="Target type"
                sortKey="target_type"
                sort={sort}
                onToggle={toggle}
              />
              <th>Target ID</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={7} className="admin-muted">
                  No audit entries.
                </td>
              </tr>
            ) : (
              sorted.map((e, i) => (
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
      </div>
    </div>
  );
}
