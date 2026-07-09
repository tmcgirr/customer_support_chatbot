import type { AdminClient } from "./api";
import { BarList, type BarDatum, categorical, Donut, type DonutSlice, SERIES, TrendChart } from "./charts";
import { Icon } from "./icons";
import { useAdminQuery } from "./useAdminQuery";

type Delta = { dir: "up" | "down" | "flat"; pctText: string } | null;

/** Net change across the trend window (series holds cumulative running totals). */
function windowDelta(values: number[]): Delta {
  if (values.length < 2) return null;
  const first = values[0];
  const abs = values[values.length - 1] - first;
  const dir = abs > 0 ? "up" : abs < 0 ? "down" : "flat";
  if (first > 0) {
    const pct = Math.round((abs / first) * 100);
    return { dir, pctText: `${pct >= 0 ? "+" : ""}${pct}%` };
  }
  return { dir, pctText: `${abs >= 0 ? "+" : ""}${abs}` };
}

const nice = (key: string) => key.replace(/_/g, " ");

/** Record → sorted bars (high→low), optionally dropping the "unset" placeholder. */
function toBars(rows: Record<string, number> | undefined, omitUnset = false): BarDatum[] {
  return Object.entries(rows ?? {})
    .filter(([key]) => !(omitUnset && key === "unset"))
    .map(([key, value]) => ({ label: nice(key), value }))
    .sort((a, b) => b.value - a.value);
}

/** Record → donut slices in fixed categorical order (color by entity, not rank hue). */
function toSlices(rows: Record<string, number> | undefined, omitUnset = false): DonutSlice[] {
  return Object.entries(rows ?? {})
    .filter(([key]) => !(omitUnset && key === "unset"))
    .sort((a, b) => b[1] - a[1])
    .map(([key, value], i) => ({ label: nice(key), value, color: categorical(i) }));
}

function DeltaChip({ delta }: { delta: Delta }) {
  if (!delta) return null;
  const cls =
    delta.dir === "up"
      ? "admin-delta admin-delta-up"
      : delta.dir === "down"
        ? "admin-delta admin-delta-down"
        : "admin-delta admin-delta-flat";
  const arrow = delta.dir === "up" ? "▲" : delta.dir === "down" ? "▼" : "→";
  return (
    <span className={cls}>
      {arrow} {delta.pctText}
    </span>
  );
}

function Kpi({
  label,
  value,
  icon,
  delta,
  foot,
}: {
  label: string;
  value: string | number;
  icon: string;
  delta?: Delta;
  foot: string;
}) {
  return (
    <div className="admin-kpi">
      <div className="admin-kpi-top">
        <span className="admin-kpi-label">{label}</span>
        <span className="admin-kpi-icon">
          <Icon name={icon} size={18} />
        </span>
      </div>
      <span className="admin-kpi-value">{value}</span>
      <span className="admin-kpi-foot">
        {delta ? <DeltaChip delta={delta} /> : null}
        <span>{foot}</span>
      </span>
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
  const { data: trends } = useAdminQuery(() => client.getTrends(30), onAuthError, []);

  if (loading) return <p className="admin-muted">Loading dashboard…</p>;
  if (error) return <p className="admin-error">{error}</p>;
  if (!data) return null;

  const points = trends?.points ?? [];
  const labels = points.map((p) => p.date);
  const convValues = points.map((p) => p.conversations);
  const reqValues = points.map((p) => p.requests);
  const windowFoot = points.length >= 2 ? `over ${points.length}d` : "no history yet";

  const convTotal = data.conversations.total;
  const reqTotal = data.requests.total;
  const conversion = convTotal > 0 ? `${Math.round((reqTotal / convTotal) * 100)}%` : "—";

  return (
    <div>
      <div className="admin-kpis">
        <Kpi
          label="Conversations"
          value={convTotal}
          icon="conversations"
          delta={windowDelta(convValues)}
          foot={windowFoot}
        />
        <Kpi
          label="Requests"
          value={reqTotal}
          icon="requests"
          delta={windowDelta(reqValues)}
          foot={windowFoot}
        />
        <Kpi
          label="Unresolved questions"
          value={data.unresolved_questions}
          icon="unresolved"
          foot="questions the bot escalated"
        />
        <Kpi
          label="Contact conversion"
          value={conversion}
          icon="target"
          foot="requests ÷ conversations"
        />
      </div>

      <div className="admin-grid-2">
        <TrendChart
          title="Activity — last 30 days"
          labels={labels}
          series={[
            { key: "conversations", label: "Conversations", color: SERIES.conversations, values: convValues },
            { key: "requests", label: "Requests", color: SERIES.requests, values: reqValues },
          ]}
        />
        <Donut
          title="Conversations by outcome"
          slices={toSlices(data.conversations.by_outcome, true)}
          centerLabel="Outcomes"
          emptyText="No recorded outcomes yet — most conversations are still unlabeled."
        />
      </div>

      <div className="admin-grid-3">
        <BarList title="Top topics" data={toBars(data.conversations.by_topic, true)} />
        <BarList title="Visitor intent" data={toBars(data.conversations.by_intent, true)} />
        <BarList title="Conversations by status" data={toBars(data.conversations.by_status)} />
      </div>

      <div className="admin-grid-2">
        <BarList title="Requests by type" data={toBars(data.requests.by_type)} />
        <BarList title="Requests by status" data={toBars(data.requests.by_status)} />
      </div>
    </div>
  );
}
