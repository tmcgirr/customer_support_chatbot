import { useState } from "react";

import type { AdminClient, UsageLine } from "./api";
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

function labelFor(map: Record<string, string>, id: string): string {
  return map[id] ?? id;
}

function fmtUsd(n: number): string {
  return n >= 1 || n === 0 ? `$${n.toFixed(2)}` : `$${n.toFixed(4)}`;
}

function fmtNum(n: number): string {
  return n.toLocaleString();
}

function UsageTable({
  title,
  lines,
  labelMap,
  showProvider,
}: {
  title: string;
  lines: UsageLine[];
  labelMap?: Record<string, string>;
  showProvider?: boolean;
}) {
  const cols = showProvider ? 6 : 5;
  return (
    <div className="admin-card">
      <h3 className="admin-section-title">{title}</h3>
      <div className="admin-tablewrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>{showProvider ? "Model" : "Category"}</th>
              {showProvider && <th>Provider</th>}
              <th>Input</th>
              <th>Output</th>
              <th>Requests</th>
              <th>Cost</th>
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 ? (
              <tr>
                <td colSpan={cols} className="admin-muted">
                  No usage in this window.
                </td>
              </tr>
            ) : (
              lines.map((l) => (
                <tr key={l.label}>
                  <td>
                    {labelMap ? labelFor(labelMap, l.label) : l.label}
                    {!l.priced && (
                      <span className="admin-badge admin-badge-warn"> unpriced</span>
                    )}
                  </td>
                  {showProvider && <td>{labelFor(PROVIDER_LABELS, l.provider)}</td>}
                  <td>{fmtNum(l.input_tokens)}</td>
                  <td>{fmtNum(l.output_tokens)}</td>
                  <td>{fmtNum(l.requests)}</td>
                  <td>{fmtUsd(l.cost_usd)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
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

  return (
    <div>
      <div className="admin-filters">
        <label>
          Window{" "}
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
          <div className="admin-card">
            <div className="admin-section-head">
              <h3 className="admin-section-title">LLM spend — last {data.window_days} days</h3>
              <span className="admin-badge admin-badge-good">{fmtUsd(data.total_cost_usd)}</span>
            </div>
            <p className="admin-muted">
              {fmtNum(data.total_input_tokens)} input + {fmtNum(data.total_output_tokens)} output
              tokens
            </p>

            {data.budget && (
              <div>
                <p className={data.budget.over ? "admin-error" : "admin-muted"}>
                  Month-to-date: {fmtUsd(data.budget.month_to_date_usd)} of{" "}
                  {fmtUsd(data.budget.monthly_usd)} budget ({data.budget.pct}%)
                  {data.budget.over ? " — over budget" : ""}
                </p>
                <div
                  style={{
                    background: "rgba(148,163,184,0.25)",
                    borderRadius: 4,
                    height: 8,
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      width: `${Math.min(data.budget.pct, 100)}%`,
                      height: "100%",
                      background: data.budget.over ? "#dc2626" : "#16a34a",
                    }}
                  />
                </div>
              </div>
            )}

            {data.unpriced_models.length > 0 && (
              <p className="admin-badge admin-badge-warn">
                {data.unpriced_models.length} unpriced model(s) — set LLM_PRICING to value them:{" "}
                {data.unpriced_models.join(", ")}
              </p>
            )}
          </div>

          <div className="admin-card-grid">
            {data.providers.map((p) => {
              const line = data.by_provider.find((l) => l.label === p.provider);
              const key = p.key_last4
                ? `••••${p.key_last4}`
                : p.configured
                  ? "configured"
                  : "not set";
              return (
                <div key={p.provider} className="admin-card">
                  <div className="admin-section-head">
                    <strong>{labelFor(PROVIDER_LABELS, p.provider)}</strong>
                    {p.active && <span className="admin-badge admin-badge-good">active</span>}
                  </div>
                  <p className="admin-muted">Model: {p.model}</p>
                  <p className="admin-muted">API key: {key}</p>
                  <p className="admin-muted">
                    Cost: {fmtUsd(line?.cost_usd ?? 0)} ·{" "}
                    {fmtNum((line?.input_tokens ?? 0) + (line?.output_tokens ?? 0))} tokens
                  </p>
                </div>
              );
            })}
          </div>

          <UsageTable title="By category" lines={data.by_category} labelMap={CATEGORY_LABELS} />
          <UsageTable title="By model" lines={data.by_model} showProvider />
        </>
      )}
    </div>
  );
}
