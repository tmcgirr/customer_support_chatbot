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

// ---- Response shapes (match the backend admin contract) --------------------

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
  contact_email: string;
  contact_company: string | null;
  conversation_id: string;
  created_at: string;
}

export interface RequestsResponse {
  requests: AdminRequest[];
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
  getDashboard(): Promise<DashboardResponse>;
  listConversations(): Promise<ConversationsResponse>;
  getConversation(id: string): Promise<ConversationDetailResponse>;
  listRequests(filters?: RequestFilters): Promise<RequestsResponse>;
  listUnresolved(): Promise<UnresolvedResponse>;
}

function basicHeader(creds: AdminCreds): string {
  return `Basic ${btoa(`${creds.username}:${creds.password}`)}`;
}

export function createAdminClient(creds: AdminCreds): AdminClient {
  async function request<T>(path: string): Promise<T> {
    const response = await fetch(`${API_BASE}/api/v1/admin${path}`, {
      headers: {
        Authorization: basicHeader(creds),
        Accept: "application/json",
      },
    });
    if (response.status === 401) {
      throw new AdminAuthError();
    }
    if (!response.ok) {
      throw new Error(`Request failed (${response.status})`);
    }
    return response.json() as Promise<T>;
  }

  return {
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
  };
}
