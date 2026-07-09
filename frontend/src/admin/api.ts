// Read-only admin API client. Talks to ${API_BASE}/api/v1/admin/* using HTTP
// Basic auth. Credentials are passed in explicitly (held in React memory by the
// app) and never persisted to localStorage. A 401 throws AdminAuthError so the
// app can drop back to the login screen.

import { API_BASE } from "../config";

export interface AdminCreds {
  username: string;
  password: string;
}

/** Thrown on a 401 so callers can drop back to the login screen. */
export class AdminAuthError extends Error {
  constructor(message = "Invalid admin credentials.") {
    super(message);
    this.name = "AdminAuthError";
  }
}

/**
 * Thrown on a 403 (authenticated, but the role is insufficient for a privileged
 * action). Distinct from AdminAuthError so callers can show an inline
 * "requires admin role" message instead of dropping back to the login screen.
 */
export class AdminForbiddenError extends Error {
  constructor(message = "This action requires an admin role.") {
    super(message);
    this.name = "AdminForbiddenError";
  }
}

// ---- Response shapes (match the backend admin contract) --------------------

export type AdminRole = "admin" | "viewer";

export interface MeResponse {
  username: string;
  role: AdminRole;
}

export interface DashboardResponse {
  conversations: {
    total: number;
    by_status: Record<string, number>;
    by_outcome: Record<string, number>;
    // V1.5 analytics: computed topic/intent labels ("unset" = not yet labeled).
    by_topic: Record<string, number>;
    by_intent: Record<string, number>;
  };
  requests: {
    total: number;
    by_type: Record<string, number>;
    by_status: Record<string, number>;
  };
  unresolved_questions: number;
}

export interface ConversationSummary {
  conversation_id: string;
  status: string;
  outcome: string | null;
  message_count: number;
  started_at: string;
  last_activity_at: string;
}

export interface ConversationsResponse {
  conversations: ConversationSummary[];
}

export interface ConversationMessage {
  id: string;
  role: string;
  content: string;
  status: string;
  created_at: string;
}

export interface ConversationDetailResponse {
  conversation_id: string;
  status: string;
  outcome: string | null;
  started_at: string;
  messages: ConversationMessage[];
}

export interface AdminRequest {
  request_id: string;
  type: string;
  status: string;
  reference: string;
  /** Masked in the list view; use revealRequest() for the unmasked value. */
  contact_email: string;
  contact_company: string | null;
  conversation_id: string;
  destination: string | null;
  /** Transport that delivered it: simulated (mock) / webhook / email. */
  delivery_channel: string | null;
  external_reference: string | null;
  last_delivery_error: string | null;
  created_at: string;
}

export interface RequestsResponse {
  requests: AdminRequest[];
}

/** Unmasked contact + submitted fields for a single request (admin only). */
export interface RevealedRequest {
  request_id: string;
  contact: {
    name: string | null;
    email: string;
    company: string | null;
  };
  fields: Record<string, unknown>;
}

/** A single unmasked transcript message (admin only). */
export interface RevealedMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

export interface RevealedConversation {
  conversation_id: string;
  messages: RevealedMessage[];
}

/** Result of a privileged mutation (redeliver / approve). */
export interface ActionResult {
  ok: boolean;
  detail: string;
}

export interface CanonicalAnswer {
  intent: string;
  name: string;
  status: "draft" | "approved";
  owner: string | null;
  review_date: string | null;
}

export interface CanonicalResponse {
  answers: CanonicalAnswer[];
}

/**
 * A managed knowledge document (file uploaded to the Vector Store). Provider ids
 * (OpenAI file / vector-store) are deliberately absent — the backend never exposes
 * them to the browser (invariant #6).
 */
export interface KnowledgeSource {
  source_id: string;
  title: string;
  category: string;
  /** Approved sources are attached to the store and served by retrieval. */
  approved: boolean;
  /** active | replaced | removed */
  lifecycle: string;
  /** pending | indexed | failed — Vector Store ingestion state. */
  indexing_status: string;
  version: string;
  owner: string;
  review_date: string | null;
  updated_at: string;
}

export interface KnowledgeSourcesResponse {
  sources: KnowledgeSource[];
}

/** A cluster of near-identical visitor questions within an insights report. */
export interface InsightsCluster {
  label: string;
  representative_question: string;
  sample_questions: string[];
  size: number;
  dominant_topic: string | null;
  coverage: "covered" | "unclear" | "missing" | string;
  conversation_ids: string[];
  proposed_question: string | null;
  proposed_answer: string | null;
  /** The canonical DRAFT intent to Approve (via the existing gate), if auto-drafted. */
  proposed_canonical_intent: string | null;
}

export interface InsightsReport {
  period_type: string;
  period_key: string;
  generated_at: string;
  window_start: string;
  window_end: string;
  conversations_analyzed: number;
  clusters: InsightsCluster[];
  summary: string;
}

export interface InsightsReportItem {
  report_id: string;
  period_type: string;
  period_key: string;
  generated_at: string;
  conversations_analyzed: number;
  cluster_count: number;
}

export interface AuditEntry {
  actor: string;
  role: string;
  action: string;
  target_type: string;
  target_id: string;
  reason: string | null;
  at: string;
}

export interface AuditResponse {
  entries: AuditEntry[];
}

export interface UnresolvedQuestion {
  question: string;
  at: string;
  conversation_id: string;
}

export interface UnresolvedResponse {
  questions: UnresolvedQuestion[];
}

export interface PrivacyRequest {
  request_id: string;
  type: "access" | "deletion";
  /** Masked in the list view (e.g. "j***@e***.com"). */
  requester_email: string;
  conversation_id: string | null;
  verification_status: "pending" | "verified" | "rejected";
  status: "open" | "completed" | "failed";
  /** Per-store counts of what an access/erasure touched, or null before completion. */
  result_counts: Record<string, number> | null;
  created_at: string;
  completed_at: string | null;
}

export interface PrivacyRequestsResponse {
  requests: PrivacyRequest[];
}

export interface RequestFilters {
  type?: string;
  status?: string;
}

export interface AdminClient {
  getMe(): Promise<MeResponse>;
  getDashboard(): Promise<DashboardResponse>;
  listConversations(): Promise<ConversationsResponse>;
  getConversation(id: string): Promise<ConversationDetailResponse>;
  listRequests(filters?: RequestFilters): Promise<RequestsResponse>;
  listUnresolved(): Promise<UnresolvedResponse>;
  listCanonical(): Promise<CanonicalResponse>;
  listAudit(): Promise<AuditResponse>;
  listPrivacyRequests(): Promise<PrivacyRequestsResponse>;
  listKnowledgeSources(): Promise<KnowledgeSourcesResponse>;
  // Privileged actions (admin role; 403 → AdminForbiddenError for a viewer).
  revealRequest(id: string, reason: string): Promise<RevealedRequest>;
  revealConversation(id: string, reason: string): Promise<RevealedConversation>;
  redeliver(id: string, reason: string): Promise<ActionResult>;
  approveCanonical(intent: string, reason: string): Promise<ActionResult>;
  verifyPrivacyRequest(id: string, reason: string): Promise<ActionResult>;
  // Knowledge management (admin role). Upload/replace send multipart form data.
  uploadKnowledge(
    file: File,
    title: string,
    category: string,
    reason: string,
  ): Promise<KnowledgeSource>;
  approveKnowledge(sourceId: string, reason: string): Promise<KnowledgeSource>;
  removeKnowledge(sourceId: string, reason: string): Promise<KnowledgeSource>;
  replaceKnowledge(sourceId: string, file: File, reason: string): Promise<KnowledgeSource>;
  // Conversation insights (V1.5).
  getLatestInsights(): Promise<{ report: InsightsReport | null }>;
  listInsightsReports(): Promise<{ reports: InsightsReportItem[] }>;
  getInsightsReport(reportId: string): Promise<InsightsReport>;
  runInsights(): Promise<ActionResult>; // admin-only; enqueues a background run
}

function basicHeader(creds: AdminCreds): string {
  return `Basic ${btoa(`${creds.username}:${creds.password}`)}`;
}

export function createAdminClient(creds: AdminCreds): AdminClient {
  async function handle<T>(response: Response): Promise<T> {
    if (response.status === 401) {
      throw new AdminAuthError();
    }
    if (response.status === 403) {
      throw new AdminForbiddenError();
    }
    if (!response.ok) {
      // Validation / business errors return { error: { code, message, ... } }.
      // Surface the message when present so views can explain the failure.
      let message = `Request failed (${response.status})`;
      try {
        const payload = (await response.json()) as { error?: { message?: string } };
        if (payload?.error?.message) message = payload.error.message;
      } catch {
        // Non-JSON body — keep the generic message.
      }
      throw new Error(message);
    }
    return response.json() as Promise<T>;
  }

  async function request<T>(
    path: string,
    options: { method?: string; body?: unknown } = {},
  ): Promise<T> {
    const headers: Record<string, string> = {
      Authorization: basicHeader(creds),
      Accept: "application/json",
    };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    const response = await fetch(`${API_BASE}/api/v1/admin${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
    return handle<T>(response);
  }

  /**
   * POST multipart/form-data (file uploads). We deliberately do NOT set
   * Content-Type — the browser adds it with the correct multipart boundary.
   */
  async function requestForm<T>(path: string, form: FormData): Promise<T> {
    const response = await fetch(`${API_BASE}/api/v1/admin${path}`, {
      method: "POST",
      headers: { Authorization: basicHeader(creds), Accept: "application/json" },
      body: form,
    });
    return handle<T>(response);
  }

  return {
    getMe: () => request<MeResponse>("/me"),
    getDashboard: () => request<DashboardResponse>("/dashboard"),
    listConversations: () => request<ConversationsResponse>("/conversations"),
    getConversation: (id: string) =>
      request<ConversationDetailResponse>(`/conversations/${encodeURIComponent(id)}`),
    listRequests: (filters?: RequestFilters) => {
      const params = new URLSearchParams();
      if (filters?.type) params.set("type", filters.type);
      if (filters?.status) params.set("status", filters.status);
      const query = params.toString();
      return request<RequestsResponse>(`/requests${query ? `?${query}` : ""}`);
    },
    listUnresolved: () => request<UnresolvedResponse>("/unresolved-questions"),
    listCanonical: () => request<CanonicalResponse>("/canonical"),
    listAudit: () => request<AuditResponse>("/audit"),
    listPrivacyRequests: () => request<PrivacyRequestsResponse>("/privacy-requests"),
    listKnowledgeSources: () => request<KnowledgeSourcesResponse>("/knowledge-sources"),
    revealRequest: (id: string, reason: string) =>
      request<RevealedRequest>(`/requests/${encodeURIComponent(id)}/reveal`, {
        method: "POST",
        body: { reason },
      }),
    revealConversation: (id: string, reason: string) =>
      request<RevealedConversation>(`/conversations/${encodeURIComponent(id)}/reveal`, {
        method: "POST",
        body: { reason },
      }),
    redeliver: (id: string, reason: string) =>
      request<ActionResult>(`/requests/${encodeURIComponent(id)}/redeliver`, {
        method: "POST",
        body: { reason },
      }),
    approveCanonical: (intent: string, reason: string) =>
      request<ActionResult>(`/canonical/${encodeURIComponent(intent)}/approve`, {
        method: "POST",
        body: { reason },
      }),
    verifyPrivacyRequest: (id: string, reason: string) =>
      request<ActionResult>(`/privacy-requests/${encodeURIComponent(id)}/verify`, {
        method: "POST",
        body: { reason },
      }),
    uploadKnowledge: (file: File, title: string, category: string, reason: string) => {
      const form = new FormData();
      form.append("file", file);
      form.append("title", title);
      form.append("category", category);
      form.append("reason", reason);
      return requestForm<KnowledgeSource>("/knowledge-sources", form);
    },
    approveKnowledge: (sourceId: string, reason: string) =>
      request<KnowledgeSource>(`/knowledge-sources/${encodeURIComponent(sourceId)}/approve`, {
        method: "POST",
        body: { reason },
      }),
    removeKnowledge: (sourceId: string, reason: string) =>
      request<KnowledgeSource>(`/knowledge-sources/${encodeURIComponent(sourceId)}/remove`, {
        method: "POST",
        body: { reason },
      }),
    replaceKnowledge: (sourceId: string, file: File, reason: string) => {
      const form = new FormData();
      form.append("file", file);
      form.append("reason", reason);
      return requestForm<KnowledgeSource>(
        `/knowledge-sources/${encodeURIComponent(sourceId)}/replace`,
        form,
      );
    },
    getLatestInsights: () => request<{ report: InsightsReport | null }>("/insights"),
    listInsightsReports: () => request<{ reports: InsightsReportItem[] }>("/insights/reports"),
    getInsightsReport: (reportId: string) =>
      request<InsightsReport>(`/insights/reports/${encodeURIComponent(reportId)}`),
    runInsights: () => request<ActionResult>("/insights/run", { method: "POST" }),
  };
}
