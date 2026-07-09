// The only module that talks to the Cadre backend. The send-message endpoint is
// POST with an SSE response, so it uses fetch + a stream reader (EventSource is
// GET-only). The session token lives in memory and is passed in per call — never
// stored in localStorage.

import { API_BASE } from "../config";
import type {
  CreateConversationResponse,
  StreamEvent,
  StreamEventName,
  SubmitRequestPayload,
  SubmitRequestResponse,
  TranscriptResponse,
} from "../types";

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public retryable = false,
    public status = 0,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = await response.json();
    const error = body?.error ?? {};
    return new ApiError(
      error.code ?? "INTERNAL_ERROR",
      error.message ?? "Something went wrong.",
      Boolean(error.retryable),
      response.status,
    );
  } catch {
    return new ApiError("INTERNAL_ERROR", "Something went wrong.", false, response.status);
  }
}

export async function createConversation(entryPage?: string): Promise<CreateConversationResponse> {
  const response = await fetch(`${API_BASE}/api/v1/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      entry_page: entryPage ?? (typeof window !== "undefined" ? window.location.pathname : "/"),
      consent_version: undefined,
    }),
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

/**
 * Fetch the stored transcript to resume a conversation after a reload or a dropped
 * stream. Throws ApiError (401 UNAUTHORIZED_SESSION on an expired token, 404 if the
 * conversation is gone) so the caller can decide to re-create.
 */
export async function getTranscript(
  conversationId: string,
  token: string,
  signal?: AbortSignal,
): Promise<TranscriptResponse> {
  const response = await fetch(`${API_BASE}/api/v1/conversations/${conversationId}/messages`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    signal,
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

function parseFrame(frame: string): StreamEvent | null {
  let event = "";
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!event) return null;
  let parsed: Record<string, unknown> = {};
  if (data) {
    try {
      parsed = JSON.parse(data);
    } catch {
      parsed = {};
    }
  }
  return { event: event as StreamEventName, data: parsed };
}

/**
 * POST a message and stream the SSE response, invoking `onEvent` per frame.
 * Reuse the same `clientMessageId` when retrying the same message (idempotency).
 * Throws ApiError for a non-2xx (e.g. 409 CONVERSATION_BUSY) before any stream.
 */
export async function sendMessage(
  conversationId: string,
  token: string,
  content: string,
  clientMessageId: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ content, client_message_id: clientMessageId }),
    signal,
  });
  if (!response.ok || !response.body) throw await toApiError(response);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    // Normalize CRLF so \n\n frame boundaries hold even through proxies that rewrite
    // line endings.
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const event = parseFrame(frame);
      if (event) onEvent(event);
      boundary = buffer.indexOf("\n\n");
    }
  }
  // Flush a final frame that wasn't terminated by a blank line.
  const trailing = buffer.trim();
  if (trailing) {
    const event = parseFrame(trailing);
    if (event) onEvent(event);
  }
}

export async function submitRequest(
  token: string,
  payload: SubmitRequestPayload,
  idempotencyKey: string,
): Promise<SubmitRequestResponse> {
  const response = await fetch(`${API_BASE}/api/v1/requests`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function submitFeedback(
  token: string,
  messageId: string,
  rating: string,
  reason?: string,
  comment?: string,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/messages/${messageId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ rating, reason, comment }),
  });
  if (!response.ok) throw await toApiError(response);
}

export function newClientMessageId(): string {
  return `cmid_${crypto.randomUUID()}`;
}
