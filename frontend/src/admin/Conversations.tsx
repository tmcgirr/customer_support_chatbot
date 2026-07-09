import { useState } from "react";

import type { AdminClient, AdminRole, ConversationSummary } from "./api";
import ConversationDetail from "./ConversationDetail";
import { distinct, FilterSelect, SortHeader, useSort } from "./tableControls";
import { useAdminQuery } from "./useAdminQuery";

const SORT: Record<string, (c: ConversationSummary) => string | number | null | undefined> = {
  status: (c) => c.status,
  outcome: (c) => c.outcome,
  messages: (c) => c.message_count,
  last_activity: (c) => c.last_activity_at,
};

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
  const [status, setStatus] = useState("");
  const [outcome, setOutcome] = useState("");
  const { data, loading, error } = useAdminQuery(() => client.listConversations(), onAuthError, []);

  const all = data?.conversations ?? [];
  const filtered = all.filter(
    (c) => (!status || c.status === status) && (!outcome || (c.outcome ?? "") === outcome),
  );
  const { sorted, sort, toggle } = useSort(filtered, SORT, { key: "last_activity", dir: "desc" });

  if (selectedId) {
    return (
      <div>
        <button type="button" className="admin-link" onClick={() => setSelectedId(null)}>
          ← Back to conversations
        </button>
        <ConversationDetail id={selectedId} client={client} role={role} onAuthError={onAuthError} />
      </div>
    );
  }

  if (loading) return <p className="admin-muted">Loading conversations…</p>;
  if (error) return <p className="admin-error">{error}</p>;
  if (!data) return null;

  return (
    <div>
      <div className="admin-filters">
        <FilterSelect
          label="Status"
          value={status}
          options={distinct(all, (c) => c.status)}
          onChange={setStatus}
        />
        <FilterSelect
          label="Outcome"
          value={outcome}
          options={distinct(all, (c) => c.outcome)}
          onChange={setOutcome}
        />
        <span className="admin-muted">
          {sorted.length} of {all.length}
        </span>
      </div>

      <div className="admin-tablewrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Conversation ID</th>
              <th>Summary</th>
              <SortHeader label="Status" sortKey="status" sort={sort} onToggle={toggle} />
              <SortHeader label="Outcome" sortKey="outcome" sort={sort} onToggle={toggle} />
              <SortHeader label="Messages" sortKey="messages" sort={sort} onToggle={toggle} numeric />
              <SortHeader
                label="Last activity"
                sortKey="last_activity"
                sort={sort}
                onToggle={toggle}
              />
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={6} className="admin-muted">
                  No conversations.
                </td>
              </tr>
            ) : (
              sorted.map((c) => (
                <tr
                  key={c.conversation_id}
                  className="admin-row-clickable"
                  onClick={() => setSelectedId(c.conversation_id)}
                >
                  <td>{c.conversation_id}</td>
                  <td className="admin-content">
                    {c.summary ?? <span className="admin-muted">—</span>}
                  </td>
                  <td>{c.status}</td>
                  <td>{c.outcome ?? "—"}</td>
                  <td className="admin-num">{c.message_count}</td>
                  <td>{c.last_activity_at}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
