// Conversation state machine for the chat widget. Owns the session (token in memory
// only), the message list, and the streaming lifecycle. Presentational components are
// driven entirely by the values this hook returns.

import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createConversation,
  newClientMessageId,
  sendMessage,
  submitFeedback,
} from "../api/client";
import type {
  ChatMessage,
  FeedbackRating,
  FeedbackReason,
  StreamEvent,
  SuggestedAction,
  WelcomePayload,
} from "../types";
import { ERROR_COPY, MAX_MESSAGE_LENGTH } from "./copy";

export type ConversationStatus = "creating" | "ready" | "streaming" | "error";

export interface UseConversationResult {
  welcome: WelcomePayload | null;
  messages: ChatMessage[];
  status: ConversationStatus;
  error: string | null;
  conversationId: string | null;
  sessionToken: string | null;
  canSend: boolean;
  send: (content: string) => void;
  retryLast: () => void;
  rate: (messageId: string, rating: FeedbackRating, reason?: FeedbackReason) => void;
  clearError: () => void;
}

interface LastSend {
  content: string;
  clientMessageId: string;
}

// Deterministic id for the streaming placeholder so retries (same client_message_id)
// replace the previous failed turn instead of stacking a second one.
function placeholderId(clientMessageId: string): string {
  return `pending_${clientMessageId}`;
}

export function useConversation(): UseConversationResult {
  const [welcome, setWelcome] = useState<WelcomePayload | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<ConversationStatus>("creating");
  const [error, setError] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [sessionToken, setSessionToken] = useState<string | null>(null);

  // Refs mirror the live session so async callbacks never read stale closures.
  const conversationIdRef = useRef<string | null>(null);
  const sessionTokenRef = useRef<string | null>(null);
  const lastSendRef = useRef<LastSend | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const startedRef = useRef(false);

  useEffect(() => {
    // Guard against React StrictMode double-invoke creating two conversations.
    if (startedRef.current) return;
    startedRef.current = true;

    let cancelled = false;
    setStatus("creating");
    createConversation()
      .then((res) => {
        if (cancelled) return;
        conversationIdRef.current = res.conversation_id;
        sessionTokenRef.current = res.session_token;
        setConversationId(res.conversation_id);
        setSessionToken(res.session_token);
        setWelcome(res.welcome);
        setStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setError(ERROR_COPY.generalFailure);
        setStatus("error");
      });

    return () => {
      cancelled = true;
      // Allow a StrictMode remount (dev) to re-create the conversation instead of
      // getting permanently stuck on "creating" after the first attempt is cancelled.
      startedRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  // Runs one assistant turn. `appendUserMessage` is false on retry (the user bubble
  // already exists and we reuse the original client_message_id for idempotency).
  const runTurn = useCallback(
    (content: string, clientMessageId: string, appendUserMessage: boolean) => {
      const cid = conversationIdRef.current;
      const token = sessionTokenRef.current;
      if (!cid || !token) return;

      const assistantId = placeholderId(clientMessageId);
      lastSendRef.current = { content, clientMessageId };

      setError(null);
      setStatus("streaming");
      setMessages((prev) => {
        // Drop any prior failed/partial assistant turn for this same message id.
        const cleaned = prev.filter((m) => m.id !== assistantId);
        const additions: ChatMessage[] = [];
        if (appendUserMessage) {
          additions.push({
            id: `user_${clientMessageId}`,
            role: "user",
            content,
            status: "completed",
            suggestedActions: [],
            clientMessageId,
          });
        }
        additions.push({
          id: assistantId,
          role: "assistant",
          content: "",
          status: "streaming",
          suggestedActions: [],
          clientMessageId,
        });
        return [...cleaned, ...additions];
      });

      const controller = new AbortController();
      abortRef.current = controller;

      let terminalSeen = false;
      const onEvent = (evt: StreamEvent) => {
        switch (evt.event) {
          case "response.delta": {
            const text = typeof evt.data.text === "string" ? evt.data.text : "";
            if (!text) return;
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + text } : m)),
            );
            break;
          }
          case "response.completed": {
            const finalId =
              typeof evt.data.assistant_message_id === "string"
                ? evt.data.assistant_message_id
                : assistantId;
            const actions = (evt.data.suggested_actions as SuggestedAction[] | undefined) ?? [];
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, id: finalId, status: "completed", suggestedActions: actions }
                  : m,
              ),
            );
            terminalSeen = true;
            setStatus("ready");
            break;
          }
          case "response.failed": {
            // Keep whatever text streamed so far; mark the turn failed and offer retry.
            setMessages((prev) =>
              prev.map((m) => (m.id === assistantId ? { ...m, status: "failed" } : m)),
            );
            terminalSeen = true;
            setError(ERROR_COPY.generalFailure);
            setStatus("error");
            break;
          }
          case "limit.reached": {
            // No assistant text is produced; remove the placeholder and surface the cap.
            setMessages((prev) => prev.filter((m) => m.id !== assistantId));
            terminalSeen = true;
            setError(ERROR_COPY.cap);
            setStatus("ready");
            break;
          }
          default:
            break;
        }
      };

      sendMessage(cid, token, content, clientMessageId, onEvent, controller.signal)
        .then(() => {
          // Stream closed cleanly but with no terminal event (proxy/LB drop): don't
          // hang in "streaming" — keep any partial text, mark failed, offer retry.
          if (controller.signal.aborted || terminalSeen) return;
          setMessages((prev) =>
            prev.flatMap((m) => {
              if (m.id !== assistantId) return [m];
              return m.content.length > 0 ? [{ ...m, status: "failed" as const }] : [];
            }),
          );
          setError(ERROR_COPY.generalFailure);
          setStatus("error");
        })
        .catch((err) => {
          if (controller.signal.aborted) return;

        // Map a pre-stream ApiError to its copy; anything else is a general failure.
        let copy: string = ERROR_COPY.generalFailure;
        if (err instanceof ApiError) {
          if (err.code === "MESSAGE_TOO_LONG") copy = ERROR_COPY.tooLong;
          else if (err.code === "CONVERSATION_BUSY") copy = ERROR_COPY.busy;
          else if (err.code === "RETRIEVAL_UNAVAILABLE") copy = ERROR_COPY.retrieval;
        }

        setMessages((prev) =>
          prev.flatMap((m) => {
            if (m.id !== assistantId) return [m];
            // Disconnect mid-stream: keep the partial text, mark failed. Pure pre-stream
            // errors have an empty placeholder, which we drop.
            if (m.content.length > 0) return [{ ...m, status: "failed" as const }];
            return [];
          }),
        );
        setError(copy);
        setStatus("error");
      });
    },
    [],
  );

  const send = useCallback(
    (content: string) => {
      if (status === "streaming" || status === "creating") return;
      if (content.length > MAX_MESSAGE_LENGTH) {
        setError(ERROR_COPY.tooLong);
        return;
      }
      runTurn(content, newClientMessageId(), true);
    },
    [runTurn, status],
  );

  const retryLast = useCallback(() => {
    const last = lastSendRef.current;
    if (!last) return;
    if (status === "streaming" || status === "creating") return;
    // Reuse the original client_message_id so the backend replays idempotently.
    runTurn(last.content, last.clientMessageId, false);
  }, [runTurn, status]);

  const rate = useCallback(
    (messageId: string, rating: FeedbackRating, reason?: FeedbackReason) => {
      const token = sessionTokenRef.current;
      if (!token) return;
      // Feedback is best-effort; failures never disrupt the conversation.
      void submitFeedback(token, messageId, rating, reason).catch(() => undefined);
    },
    [],
  );

  const clearError = useCallback(() => setError(null), []);

  const canSend = status !== "streaming" && status !== "creating";

  return {
    welcome,
    messages,
    status,
    error,
    conversationId,
    sessionToken,
    canSend,
    send,
    retryLast,
    rate,
    clearError,
  };
}
