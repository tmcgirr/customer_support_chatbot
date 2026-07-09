import { useState } from "react";

import type { AdminClient, UnresolvedQuestion } from "./api";
import { SortHeader, useSort } from "./tableControls";
import { useAdminQuery } from "./useAdminQuery";

const SORT: Record<string, (q: UnresolvedQuestion) => string | number | null | undefined> = {
  at: (q) => q.at,
};

export default function Unresolved({
  client,
  onAuthError,
}: {
  client: AdminClient;
  onAuthError: () => void;
}) {
  const [query, setQuery] = useState("");
  const { data, loading, error } = useAdminQuery(() => client.listUnresolved(), onAuthError, []);

  const all = data?.questions ?? [];
  const needle = query.trim().toLowerCase();
  const filtered = needle
    ? all.filter((q) => q.question.toLowerCase().includes(needle))
    : all;
  const { sorted, sort, toggle } = useSort(filtered, SORT, { key: "at", dir: "desc" });

  if (loading) return <p className="admin-muted">Loading unresolved questions…</p>;
  if (error) return <p className="admin-error">{error}</p>;
  if (!data) return null;

  return (
    <div>
      <div className="admin-filters">
        <label>
          Search
          <input
            type="search"
            placeholder="Filter questions…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <span className="admin-muted">
          {sorted.length} of {all.length}
        </span>
      </div>

      <div className="admin-tablewrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Question</th>
              <SortHeader label="At" sortKey="at" sort={sort} onToggle={toggle} />
              <th>Conversation ID</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={3} className="admin-muted">
                  No unresolved questions.
                </td>
              </tr>
            ) : (
              sorted.map((q, i) => (
                <tr key={`${q.conversation_id}-${i}`}>
                  <td className="admin-content">{q.question}</td>
                  <td>{q.at}</td>
                  <td>{q.conversation_id}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
