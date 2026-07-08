// Shared widget types. Mirrors the API/data contracts (docs/04).

export interface SuggestedAction {
  id: string;
  label: string;
}

export interface WelcomePayload {
  text: string;
  suggested_actions: SuggestedAction[];
}

export interface CreateConversationResponse {
  conversation_id: string;
  session_token: string;
  welcome: WelcomePayload;
}

export type MessageRole = "user" | "assistant";
export type MessageStatus = "streaming" | "completed" | "failed" | "partial";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  status: MessageStatus;
  suggestedActions: SuggestedAction[];
  clientMessageId?: string;
}

export type StreamEventName =
  | "message.accepted"
  | "response.started"
  | "response.delta"
  | "response.citation"
  | "action.offered"
  | "response.completed"
  | "response.failed"
  | "limit.reached";

export interface StreamEvent {
  event: StreamEventName;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: Record<string, any>;
}

// --- Requests (contracts §3.4). Submitted by the browser after confirmation. ---
export type RequestType = "strategy_call" | "portal_support" | "human_escalation";

export interface Contact {
  name?: string;
  email?: string;
  company?: string;
}

export interface SubmitRequestPayload {
  type: RequestType;
  conversation_id: string;
  contact: Contact;
  fields: Record<string, unknown>;
  consent_version: string;
  confirmed: boolean;
}

export interface SubmitRequestResponse {
  request_id: string;
  status: string;
  reference: string;
  // A duplicate Idempotency-Key replays the original with HTTP 200 (contracts §9).
  duplicate?: boolean;
}

export type FeedbackRating = "helpful" | "not_helpful";
export type FeedbackReason = "incorrect" | "unclear" | "did_not_answer" | "need_person" | "other";
