import { useState } from "react";

import type { AdminClient, UsageLine } from "./api";
import { Icon } from "./icons";
import { SortHeader, useSort } from "./tableControls";
import { useAdminQuery } from "./useAdminQuery";

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI (GPT)",
  anthropic: "Anthropic (Claude)",
  openrouter: "OpenRouter",
};

const CATEGORY_LABELS: Record<string, string> = {
  chat: "Chat (production)",
  testing: "Testing / eval",
  summary: "Summaries",
  insights: "Insights",
  labeling: "Labeling",
  embeddings: "Embeddings",
};

const WINDOWS = [7, 30, 90];

const SORT: Record<string, (l: UsageLine) => string | number> = {
  label: (l) => l.label,
  provider: (l) => l.provider,
  input_tokens: (l) => l.input_tokens,
  output_tokens: (l) => l.output_tokens,
  requests: (l) => l.requests,
  cost_usd: (l) => l.cost_usd,
};

function labelFor(map: Record<string, string>, id: string): string {
  return map[id] ?? id;
}

function fmtUsd(n: number): string {
  return n >= 1 || n === 0 ? `$${n.toFixed(2)}` : `$${n.toFixed(4)}`;
}

function fmtNum(n: number): string {
  return n.toLocaleString();
}

function Kpi({
  label,
  value,
  icon,
  foot,
}: {
  label: string;
  value: string;
  icon: string;
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
        <span>{foot}</span>
      </span>
    </div>
  );
}

function UsageTable({
  lines,
  labelMap,
  columnLabel,
  showProvider,
}: {
  lines: UsageLine[];
  labelMap?: Record<string, string>;
  columnLabel: string;
  showProvider?: boolean;
}) {
  const { sorted, sort, toggle } = useSort(lines, SORT, { key: "cost_usd", dir: "desc" });
  const cols = showProvider ? 6 : 5;
  return (
    <div className="admin-tablewrap">
      <table className="admin-table">
        <thead>
          <tr>
            <SortHeader label={columnLabel} sortKey="label" sort={sort} onToggle={toggle} />
            {showProvider && (
              <SortHeader label="Provider" sortKey="provider" sort={sort} onToggle={toggle} />
            )}
            <SortHeader label="Input" sortKey="input_tokens" sort={sort} onToggle={toggle} numeric />
            <SortHeader
              label="Output"
              sortKey="output_tokens"
              sort={sort}
              onToggle={toggle}
              numeric
            />
            <SortHeader label="Requests" sortKey="requests" sort={sort} onToggle={toggle} numeric />
            <SortHeader label="Cost" sortKey="cost_usd" sort={sort} onToggle={toggle} numeric />
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr>
              <td colSpan={cols} className="admin-muted">
                No usage in this window.
              </td>
            </tr>
          ) : (
            sorted.map((l) => (
              <tr key={l.label}>
                <td>
                  {labelMap ? labelFor(labelMap, l.label) : l.label}
                  {!l.priced && <span className="admin-badge admin-badge-warn"> unpriced</span>}
                </td>
                {showProvider && <td>{labelFor(PROVIDER_LABELS, l.provider)}</td>}
                <td className="admin-num">{fmtNum(l.input_tokens)}</td>
                <td className="admin-num">{fmtNum(l.output_tokens)}</td>
                <td className="admin-num">{fmtNum(l.requests)}</td>
                <td className="admin-num">{fmtUsd(l.cost_usd)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

/**
 * LLM usage + cost visibility (read-only). Token spend per provider / model / category,
 * the active model + masked API key per provider, and a month-to-date budget bar. The API
 * key tail is only present for admins (the server omits it for viewers).
 */
export default function Usage({
  client,
  onAuthError,
}: {
  client: AdminClient;
  onAuthError: () => void;
}) {
  const [windowDays, setWindowDays] = useState(30);
  const { data, loading, error } = useAdminQuery(
    () => client.getUsage(windowDays),
    onAuthError,
    [windowDays],
  );

  const totalRequests = data ? data.by_provider.reduce((sum, l) => sum + l.requests, 0) : 0;

  return (
    <div>
      <p className="admin-page-intro">
        LLM token usage and estimated cost across providers, models, and categories. Costs use the
        configured pricing; unpriced models are flagged. Read-only.
      </p>

      <div className="admin-filters">
        <label>
          Window
          <select value={windowDays} onChange={(e) => setWindowDays(Number(e.target.value))}>
            {WINDOWS.map((d) => (
              <option key={d} value={d}>
                {d} days
              </option>
            ))}
          </select>
        </label>
      </div>

      {loading && <p className="admin-muted">Loading usage…</p>}
      {error && <p className="admin-error">{error}</p>}

      {data && (
        <>
          <div className="admin-kpis">
            <Kpi
              label="Total cost"
              value={fmtUsd(data.total_cost_usd)}
              icon="cost"
              foot={`last ${data.window_days} days`}
            />
            <Kpi label="Input tokens" value={fmtNum(data.total_input_tokens)} icon="model" foot="prompt" />
            <Kpi
              label="Output tokens"
              value={fmtNum(data.total_output_tokens)}
              icon="model"
              foot="completion"
            />
            <Kpi
              label="LLM requests"
              value={fmtNum(totalRequests)}
              icon="requests"
              foot={`last ${data.window_days} days`}
            />
          </div>

          {data.budget && (
            <section className="admin-section">
              <div className="admin-section-head">
                <h3 className="admin-section-title">Monthly budget</h3>
                <span className={data.budget.over ? "admin-error" : "admin-section-sub"}>
                  Month-to-date: {fmtUsd(data.budget.month_to_date_usd)} of{" "}
                  {fmtUsd(data.budget.monthly_usd)} ({data.budget.pct}%)
                  {data.budget.over ? " — over budget" : ""}
                </span>
              </div>
              <div className="admin-progress">
                <div
                  className="admin-progress-bar"
                  data-over={data.budget.over}
                  style={{ width: `${Math.min(data.budget.pct, 100)}%` }}
                />
              </div>
            </section>
          )}

          {data.unpriced_models.length > 0 && (
            <div className="admin-notice admin-notice-info">
              <span className="admin-notice-icon">
                <Icon name="unresolved" size={16} />
              </span>
              <span>
                {data.unpriced_models.length} unpriced model
                {data.unpriced_models.length === 1 ? "" : "s"} — set <code>LLM_PRICING</code> to
                value {data.unpriced_models.length === 1 ? "it" : "them"}:{" "}
                {data.unpriced_models.join(", ")}
              </span>
            </div>
          )}

          <section className="admin-section">
            <div className="admin-section-head">
              <h3 className="admin-section-title">Providers</h3>
            </div>
            <div className="admin-card-grid">
              {data.providers.map((p) => {
                const line = data.by_provider.find((l) => l.label === p.provider);
                const key = p.key_last4
                  ? `••••${p.key_last4}`
                  : p.configured
                    ? "configured"
                    : "not set";
                const tokens = (line?.input_tokens ?? 0) + (line?.output_tokens ?? 0);
                return (
                  <div key={p.provider} className="admin-card">
                    <div className="admin-cluster-head">
                      <strong className="admin-cluster-title">
                        {labelFor(PROVIDER_LABELS, p.provider)}
                      </strong>
                      {p.active && <span className="admin-badge admin-badge-good">active</span>}
                    </div>
                    <dl className="admin-kv">
                      <div className="admin-kv-row">
                        <dt>Model</dt>
                        <dd>{p.model}</dd>
                      </div>
                      <div className="admin-kv-row">
                        <dt>API key</dt>
                        <dd>{key}</dd>
                      </div>
                      <div className="admin-kv-row">
                        <dt>Cost</dt>
                        <dd>
                          {fmtUsd(line?.cost_usd ?? 0)} · {fmtNum(tokens)} tokens
                        </dd>
                      </div>
                    </dl>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="admin-section">
            <div className="admin-section-head">
              <h3 className="admin-section-title">By category</h3>
            </div>
            <UsageTable lines={data.by_category} labelMap={CATEGORY_LABELS} columnLabel="Category" />
          </section>

          <section className="admin-section">
            <div className="admin-section-head">
              <h3 className="admin-section-title">By model</h3>
            </div>
            <UsageTable lines={data.by_model} columnLabel="Model" showProvider />
          </section>
        </>
      )}
    </div>
  );
}
