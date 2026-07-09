import type { AdminClient, FunnelStage } from "./api";
import { useAdminQuery } from "./useAdminQuery";

const STAGES: { key: keyof FunnelStage; label: string }[] = [
  { key: "visited", label: "Visited" },
  { key: "asked", label: "Asked" },
  { key: "engaged", label: "Engaged" },
  { key: "requested", label: "Requested contact" },
];

function pct(n: number, d: number): number {
  return d > 0 ? Math.round((n / d) * 100) : 0;
}

function OverallFunnel({ stage }: { stage: FunnelStage }) {
  const top = stage.visited;
  return (
    <div className="admin-card">
      <h3>Conversion funnel</h3>
      {STAGES.map((s) => {
        const count = stage[s.key];
        const width = pct(count, top);
        return (
          <div key={s.key} className="admin-funnel-row">
            <span className="admin-funnel-label">{s.label}</span>
            <span className="admin-funnel-track">
              <span className="admin-funnel-bar" style={{ width: `${Math.max(width, 1)}%` }} />
            </span>
            <span className="admin-funnel-count">
              {count} ({width}%)
            </span>
          </div>
        );
      })}
    </div>
  );
}

function BreakdownTable({
  dimension,
  rows,
}: {
  dimension: string;
  rows: Record<string, FunnelStage>;
}) {
  const entries = Object.entries(rows).sort((a, b) => b[1].visited - a[1].visited);
  return (
    <div style={{ marginTop: 20 }}>
      <div className="admin-tablewrap">
        <table className="admin-table">
        <thead>
          <tr>
            <th>{dimension}</th>
            <th className="admin-num">Visited</th>
            <th className="admin-num">Asked</th>
            <th className="admin-num">Engaged</th>
            <th className="admin-num">Requested</th>
            <th className="admin-num">Conv. %</th>
          </tr>
        </thead>
        <tbody>
          {entries.length === 0 ? (
            <tr>
              <td colSpan={6} className="admin-muted">
                No labeled conversations yet.
              </td>
            </tr>
          ) : (
            entries.map(([key, s]) => (
              <tr key={key}>
                <td>{key}</td>
                <td className="admin-num">{s.visited}</td>
                <td className="admin-num">{s.asked}</td>
                <td className="admin-num">{s.engaged}</td>
                <td className="admin-num">{s.requested}</td>
                <td className="admin-num">{pct(s.requested, s.visited)}%</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
      </div>
    </div>
  );
}

export default function Funnel({
  client,
  onAuthError,
}: {
  client: AdminClient;
  onAuthError: () => void;
}) {
  const { data, loading, error } = useAdminQuery(() => client.getFunnel(), onAuthError, []);

  if (loading) return <p className="admin-muted">Loading funnel…</p>;
  if (error) return <p className="admin-error">{error}</p>;
  if (!data) return null;

  return (
    <div>
      <p className="admin-muted">
        Visited (conversation started) → Asked (≥1 question) → Engaged (multi-turn) → Requested
        (submitted a contact request). Percentages are of Visited.
      </p>
      <OverallFunnel stage={data.overall} />
      <h3 style={{ marginTop: 24 }}>By topic</h3>
      <BreakdownTable dimension="Topic" rows={data.by_topic} />
      <h3 style={{ marginTop: 24 }}>By intent</h3>
      <BreakdownTable dimension="Intent" rows={data.by_intent} />
    </div>
  );
}
