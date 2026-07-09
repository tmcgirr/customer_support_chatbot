import { useState } from "react";

import { AdminAuthError, AdminForbiddenError } from "./api";
import type { AdminClient, AdminRole, InsightsCluster, KnowledgeGap } from "./api";
import { useAdminAction } from "./useAdminAction";
import { useAdminQuery } from "./useAdminQuery";

function coverageClass(coverage: string): string {
  if (coverage === "missing") return "admin-cov admin-cov-missing";
  if (coverage === "unclear") return "admin-cov admin-cov-unclear";
  return "admin-cov admin-cov-covered";
}

function ClusterCard({
  cluster,
  isAdmin,
  busy,
  approved,
  onApprove,
}: {
  cluster: InsightsCluster;
  isAdmin: boolean;
  busy: boolean;
  approved: boolean;
  onApprove: (intent: string) => void;
}) {
  const draftIntent = cluster.proposed_canonical_intent;
  return (
    <div className="admin-card">
      <h3>{cluster.label}</h3>
      <p>
        <span className={coverageClass(cluster.coverage)}>{cluster.coverage}</span> · asked{" "}
        {cluster.size}×{cluster.dominant_topic ? ` · ${cluster.dominant_topic}` : ""}
      </p>
      <ul className="admin-reveal-fields">
        {cluster.sample_questions.slice(0, 3).map((q, i) => (
          <li key={i}>{q}</li>
        ))}
      </ul>
      {cluster.proposed_question && (
        <div className="admin-proposed">
          <p>
            <strong>Proposed FAQ:</strong> {cluster.proposed_question}
          </p>
          {cluster.proposed_answer && <p className="admin-content">{cluster.proposed_answer}</p>}
          {isAdmin &&
            draftIntent &&
            (approved ? (
              <p className="admin-muted">Approved ✓ — now served.</p>
            ) : (
              <button
                type="button"
                className="admin-link"
                disabled={busy}
                onClick={() => onApprove(draftIntent)}
              >
                Approve FAQ
              </button>
            ))}
        </div>
      )}
    </div>
  );
}

function GapRow({
  gap,
  rank,
  isAdmin,
  busy,
  approved,
  onApprove,
}: {
  gap: KnowledgeGap;
  rank: number;
  isAdmin: boolean;
  busy: boolean;
  approved: boolean;
  onApprove: (intent: string) => void;
}) {
  const draftIntent = gap.proposed_canonical_intent;
  return (
    <li className="admin-card admin-gap">
      <div className="admin-gap-head">
        <span className="admin-gap-rank">#{rank}</span>
        <span className={coverageClass(gap.coverage)}>{gap.coverage}</span>
        <strong>{gap.label}</strong>
        <span className="admin-muted admin-gap-meta">
          asked {gap.total_asked}× · seen {gap.days_seen} day{gap.days_seen === 1 ? "" : "s"}
        </span>
      </div>
      <p className="admin-gap-q">“{gap.representative_question}”</p>
      {gap.proposed_question && (
        <div className="admin-proposed">
          <p>
            <strong>Proposed FAQ:</strong> {gap.proposed_question}
          </p>
          {gap.proposed_answer && <p className="admin-content">{gap.proposed_answer}</p>}
          {isAdmin &&
            draftIntent &&
            (approved ? (
              <p className="admin-muted">Approved ✓ — now served.</p>
            ) : (
              <button
                type="button"
                className="admin-link"
                disabled={busy}
                onClick={() => onApprove(draftIntent)}
              >
                Approve FAQ
              </button>
            ))}
        </div>
      )}
    </li>
  );
}

export default function Insights({
  client,
  role,
  onAuthError,
}: {
  client: AdminClient;
  role: AdminRole;
  onAuthError: () => void;
}) {
  const isAdmin = role === "admin";
  const [selectedId, setSelectedId] = useState("");
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [approvedIntents, setApprovedIntents] = useState<Set<string>>(new Set());
  const { error: actionError, busy, run } = useAdminAction(onAuthError);

  const { data: listData } = useAdminQuery(() => client.listInsightsReports(), onAuthError, []);
  const { data: gapsData } = useAdminQuery(() => client.getKnowledgeGaps(14), onAuthError, []);
  const gaps = gapsData?.gaps ?? [];
  const { data: reportData, loading, error } = useAdminQuery(
    () =>
      selectedId
        ? client.getInsightsReport(selectedId).then((report) => ({ report }))
        : client.getLatestInsights(),
    onAuthError,
    [selectedId],
  );
  const report = reportData?.report ?? null;

  async function handleRun() {
    if (running) return; // guard double-clicks while the request is in flight
    setRunMsg(null);
    setRunning(true);
    try {
      const result = await client.runInsights();
      setRunMsg(`${result.detail} Reports refresh shortly — reload in a minute.`);
    } catch (err: unknown) {
      if (err instanceof AdminAuthError) {
        onAuthError();
      } else if (err instanceof AdminForbiddenError) {
        setRunMsg("This action requires an admin role.");
      } else {
        setRunMsg(err instanceof Error ? err.message : "Run failed.");
      }
    } finally {
      setRunning(false);
    }
  }

  function handleApprove(intent: string) {
    run(
      "Reason for approving this proposed FAQ (audited). It becomes searchable once approved:",
      (reason) => client.approveCanonical(intent, reason),
      () => setApprovedIntents((prev) => new Set(prev).add(intent)),
    );
  }

  return (
    <div>
      <div className="admin-filters">
        <label>
          Report{" "}
          <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
            <option value="">Latest</option>
            {(listData?.reports ?? []).map((r) => (
              <option key={r.report_id} value={r.report_id}>
                {r.period_type} {r.period_key} ({r.cluster_count} clusters)
              </option>
            ))}
          </select>
        </label>
        {isAdmin && (
          <button type="button" className="admin-signout" disabled={running} onClick={handleRun}>
            {running ? "Queuing…" : "Run now"}
          </button>
        )}
      </div>

      {runMsg && <p className="admin-muted">{runMsg}</p>}
      {actionError && <p className="admin-error">{actionError}</p>}

      {gapsData && (
        <section className="admin-gaps">
          <h3>Top knowledge gaps · last {gapsData.window_days} days</h3>
          {gaps.length === 0 ? (
            <p className="admin-muted">
              {gapsData.daily_reports === 0
                ? "No daily reports yet — gaps appear once the daily insights run has data."
                : "No uncovered question themes in this window 🎉"}
            </p>
          ) : (
            <ol className="admin-gap-list">
              {gaps.map((g, i) => (
                <GapRow
                  key={g.key}
                  gap={g}
                  rank={i + 1}
                  isAdmin={isAdmin}
                  busy={busy}
                  approved={
                    g.proposed_canonical_intent
                      ? approvedIntents.has(g.proposed_canonical_intent)
                      : false
                  }
                  onApprove={handleApprove}
                />
              ))}
            </ol>
          )}
        </section>
      )}

      {loading && <p className="admin-muted">Loading insights…</p>}
      {error && <p className="admin-error">{error}</p>}
      {!loading && report === null && (
        <p className="admin-muted">
          No insights report yet.{isAdmin ? " Click “Run now” to generate one." : ""}
        </p>
      )}

      {report && (
        <div>
          <p className="admin-muted">
            {report.period_type} {report.period_key} ·{" "}
            {report.conversations_in_period > report.conversations_analyzed
              ? `${report.conversations_analyzed} of ${report.conversations_in_period} conversations (sampled)`
              : `${report.conversations_analyzed} conversations`}{" "}
            · generated {report.generated_at}
          </p>
          <div className="admin-card">
            <h3>Summary</h3>
            <p className="admin-content">{report.summary}</p>
          </div>
          {report.clusters.length === 0 ? (
            <p className="admin-muted">No notable question clusters in this period.</p>
          ) : (
            <div className="admin-card-grid">
              {report.clusters.map((c, i) => (
                <ClusterCard
                  key={i}
                  cluster={c}
                  isAdmin={isAdmin}
                  busy={busy}
                  approved={
                    c.proposed_canonical_intent
                      ? approvedIntents.has(c.proposed_canonical_intent)
                      : false
                  }
                  onApprove={handleApprove}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
