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
  // Privileged actions (admin role; 403 → AdminForbiddenError for a viewer).
  revealRequest(id: string, reason: string): Promise<RevealedRequest>;
  revealConversation(id: string, reason: string): Promise<RevealedConversation>;
  redeliver(id: string, reason: string): Promise<ActionResult>;
  approveCanonical(intent: string, reason: string): Promise<ActionResult>;
}

function basicHeader(creds: AdminCreds): string {
  return `Basic ${btoa(`${creds.username}:${creds.password}`)}`;
}

export function createAdminClient(creds: AdminCreds): AdminClient {
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
  };
}
