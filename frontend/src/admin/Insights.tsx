import { useMemo, useState } from "react";

import { AdminAuthError, AdminForbiddenError } from "./api";
import type {
  AdminClient,
  AdminRole,
  InsightsCluster,
  InsightsReport,
  InsightsReportItem,
  KnowledgeGap,
} from "./api";
import EmptyState from "./EmptyState";
import { useAdminAction } from "./useAdminAction";
import { useAdminQuery } from "./useAdminQuery";

// Report horizons, in display order. A period key reads: daily "2026-07-08",
// weekly "2026-W28", monthly "2026-07".
const HORIZONS = ["daily", "weekly", "monthly"] as const;
const HORIZON_LABEL: Record<string, string> = {
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
};

const cap = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

function periodLabel(r: InsightsReportItem): string {
  return `${r.period_key} · ${r.cluster_count} cluster${r.cluster_count === 1 ? "" : "s"}`;
}

/** "2026-07-09T20:47:29.568000Z" → "2026-07-09 20:47 UTC" (drop microseconds). */
function fmtGenerated(iso: string): string {
  return `${iso.slice(0, 16).replace("T", " ")} UTC`;
}

function coverageClass(coverage: string): string {
  if (coverage === "missing") return "admin-cov admin-cov-missing";
  if (coverage === "unclear") return "admin-cov admin-cov-unclear";
  return "admin-cov admin-cov-covered";
}

/** The proposed-FAQ footer shared by cluster cards and gap rows: the auto-drafted
 *  question/answer plus the audited Approve action (admin only). */
function ProposedFaq({
  question,
  answer,
  isAdmin,
  draftIntent,
  busy,
  approved,
  onApprove,
}: {
  question: string;
  answer: string | null;
  isAdmin: boolean;
  draftIntent: string | null;
  busy: boolean;
  approved: boolean;
  onApprove: (intent: string) => void;
}) {
  return (
    <div className="admin-proposed">
      <span className="admin-proposed-label">Proposed FAQ</span>
      <p className="admin-proposed-q">{question}</p>
      {answer && <p className="admin-proposed-a">{answer}</p>}
      {isAdmin &&
        draftIntent &&
        (approved ? (
          <span className="admin-badge admin-badge-good">Approved — now served</span>
        ) : (
          <button
            type="button"
            className="admin-btn admin-btn-ghost admin-btn-sm"
            disabled={busy}
            onClick={() => onApprove(draftIntent)}
          >
            Approve FAQ
          </button>
        ))}
    </div>
  );
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
  return (
    <div className="admin-card admin-cluster">
      <div className="admin-cluster-head">
        <strong className="admin-cluster-title">{cluster.label}</strong>
        <span className={coverageClass(cluster.coverage)}>{cluster.coverage}</span>
      </div>
      <div className="admin-cluster-meta">
        <span>asked {cluster.size}×</span>
        {cluster.dominant_topic && <span>· {cluster.dominant_topic}</span>}
      </div>
      {cluster.sample_questions.length > 0 && (
        <div className="admin-samples">
          <span className="admin-samples-label">Sample questions</span>
          <ul>
            {cluster.sample_questions.slice(0, 3).map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </div>
      )}
      {cluster.proposed_question && (
        <ProposedFaq
          question={cluster.proposed_question}
          answer={cluster.proposed_answer}
          isAdmin={isAdmin}
          draftIntent={cluster.proposed_canonical_intent}
          busy={busy}
          approved={approved}
          onApprove={onApprove}
        />
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
  return (
    <li className="admin-card admin-gap">
      <div className="admin-gap-head">
        <span className="admin-gap-rank">#{rank}</span>
        <span className={coverageClass(gap.coverage)}>{gap.coverage}</span>
        <strong className="admin-gap-title">{gap.label}</strong>
        <span className="admin-gap-meta">
          asked {gap.total_asked}× · seen {gap.days_seen} day{gap.days_seen === 1 ? "" : "s"}
        </span>
      </div>
      <p className="admin-gap-q">“{gap.representative_question}”</p>
      {gap.proposed_question && (
        <ProposedFaq
          question={gap.proposed_question}
          answer={gap.proposed_answer}
          isAdmin={isAdmin}
          draftIntent={gap.proposed_canonical_intent}
          busy={busy}
          approved={approved}
          onApprove={onApprove}
        />
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
  // Picker state is a user OVERRIDE only; the effective selection is derived below
  // so the report query is a single dependent fetch (no effect-chained double-fetch).
  const [horizon, setHorizon] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [approvedIntents, setApprovedIntents] = useState<Set<string>>(new Set());
  const { error: actionError, busy, run, dialog } = useAdminAction(onAuthError);

  const { data: listData } = useAdminQuery(() => client.listInsightsReports(), onAuthError, []);
  const { data: gapsData } = useAdminQuery(() => client.getKnowledgeGaps(14), onAuthError, []);
  const gaps = gapsData?.gaps ?? [];

  // Group the stored reports by horizon so the picker can offer Daily / Weekly /
  // Monthly, each with its own list of periods (newest first).
  const byHorizon = useMemo(() => {
    const map: Record<string, InsightsReportItem[]> = {};
    for (const r of listData?.reports ?? []) (map[r.period_type] ??= []).push(r);
    return map;
  }, [listData]);
  const availableHorizons = HORIZONS.filter((h) => byHorizon[h]?.length);
  const hasReports = (listData?.reports?.length ?? 0) > 0;

  // Effective selection: the user's pick, else default to the newest stored report.
  const effectiveHorizon = horizon || listData?.reports?.[0]?.period_type || "";
  const periods = byHorizon[effectiveHorizon] ?? [];
  const effectiveId = selectedId || periods[0]?.report_id || "";

  function pickHorizon(next: string) {
    setHorizon(next);
    setSelectedId(byHorizon[next]?.[0]?.report_id ?? "");
  }

  const { data: reportData, loading, error } = useAdminQuery<{ report: InsightsReport | null }>(
    () =>
      effectiveId
        ? client.getInsightsReport(effectiveId).then((report) => ({ report }))
        : Promise.resolve({ report: null }),
    onAuthError,
    [effectiveId],
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
    run({
      title: "Approve FAQ",
      message: "Approve this proposed FAQ? It becomes searchable once approved.",
      defaultReason: "Approved proposed FAQ via admin console",
      confirmLabel: "Approve",
      action: (reason) => client.approveCanonical(intent, reason),
      onSuccess: () => setApprovedIntents((prev) => new Set(prev).add(intent)),
    });
  }

  const runNowButton = (
    <button
      type="button"
      className="admin-btn admin-btn-primary"
      disabled={running}
      onClick={handleRun}
    >
      {running ? "Queuing…" : "Run now"}
    </button>
  );

  const reportMeta = report
    ? `${report.period_key} · ${
        report.conversations_in_period > report.conversations_analyzed
          ? `${report.conversations_analyzed} of ${report.conversations_in_period} conversations (sampled)`
          : `${report.conversations_analyzed} conversations`
      } · generated ${fmtGenerated(report.generated_at)}`
    : null;

  return (
    <div>
      {dialog}
      <p className="admin-page-intro">
        Insights cluster recent visitor questions into themes, flag which are already covered by
        an approved answer, and propose FAQs for the gaps. Each run is saved as a report for its
        period — use the Daily / Weekly / Monthly picker to browse past ones. “Run now”
        regenerates the current period (via the background worker).
      </p>

      <div className="admin-toolbar">
        {hasReports ? (
          <>
            <div className="admin-segmented" role="group" aria-label="Report horizon">
              {availableHorizons.map((h) => (
                <button
                  key={h}
                  type="button"
                  className={h === effectiveHorizon ? "admin-seg is-active" : "admin-seg"}
                  aria-pressed={h === effectiveHorizon}
                  onClick={() => pickHorizon(h)}
                >
                  {HORIZON_LABEL[h]}
                </button>
              ))}
            </div>
            <label>
              <span>Period</span>
              <select value={effectiveId} onChange={(e) => setSelectedId(e.target.value)}>
                {periods.map((r) => (
                  <option key={r.report_id} value={r.report_id}>
                    {periodLabel(r)}
                  </option>
                ))}
              </select>
            </label>
          </>
        ) : (
          <span className="admin-muted">No stored reports yet.</span>
        )}
        <span className="admin-toolbar-spacer" />
        {isAdmin && runNowButton}
      </div>

      {runMsg && <div className="admin-notice admin-notice-success">{runMsg}</div>}
      {actionError && <div className="admin-notice admin-notice-error">{actionError}</div>}

      <section className="admin-section">
        <div className="admin-section-head">
          <h3 className="admin-section-title">Top knowledge gaps</h3>
          {gapsData && <span className="admin-section-sub">last {gapsData.window_days} days</span>}
        </div>
        {!gapsData ? (
          <p className="admin-muted">Loading knowledge gaps…</p>
        ) : gaps.length === 0 ? (
          <EmptyState
            icon="unresolved"
            title={
              gapsData.daily_reports === 0
                ? "No daily reports yet"
                : "No uncovered question themes"
            }
            hint={
              gapsData.daily_reports === 0
                ? "Knowledge gaps rank the recurring questions your bot couldn’t confidently answer. They appear once the daily insights job (background worker) has recorded a few days of conversations."
                : "Every recurring question in this window is already covered by an approved answer."
            }
          />
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

      <section className="admin-section">
        <div className="admin-section-head">
          <h3 className="admin-section-title">
            {report ? `${cap(report.period_type)} report` : "Report"}
          </h3>
          {reportMeta && <span className="admin-section-sub">{reportMeta}</span>}
        </div>

        {loading ? (
          <p className="admin-muted">Loading insights…</p>
        ) : error ? (
          <div className="admin-notice admin-notice-error">{error}</div>
        ) : report === null ? (
          <EmptyState
            icon="insights"
            title="No insights report yet"
            hint={
              isAdmin
                ? "Click “Run now” to cluster your recent conversations into themes. Generation runs in the background worker and takes about a minute — reload after it finishes. (If nothing ever appears, make sure the worker process is running.)"
                : "Reports appear here once the background worker has generated one."
            }
            action={isAdmin ? runNowButton : null}
          />
        ) : (
          <div className="admin-report-body">
            <div className="admin-card">
              <h3>Summary</h3>
              <p className="admin-content">{report.summary}</p>
            </div>
            {report.clusters.length === 0 ? (
              <EmptyState
                icon="conversations"
                title="No notable question clusters"
                hint="This period didn’t have enough repeated questions to form a theme."
              />
            ) : (
              <>
                <div className="admin-subhead">
                  Question clusters ({report.clusters.length})
                </div>
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
              </>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
