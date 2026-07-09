// Conversation state machine for the chat widget. Owns the session, the message
// list, and the streaming lifecycle. Presentational components are driven entirely
// by the values this hook returns.
//
// V7 reconnect: the session (conversation id + token) is mirrored into sessionStorage
// so a page reload RESUMES the same conversation from the transcript endpoint rather
// than starting over. sessionStorage (not localStorage) is per-tab and cleared when
// the tab closes; the token is a short-lived, conversation-scoped HMAC — not a
// credential — and the server expires it independently. On a dropped stream we
// reconcile against the server transcript (the turn may have completed even though
// the SSE frame was lost); on true expiry (401) we recover by starting a new chat.

import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createConversation,
  getTranscript,
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
  TranscriptMessage,
  WelcomePayload,
} from "../types";
import { actionLabel, ERROR_COPY, MAX_MESSAGE_LENGTH } from "./copy";

export type ConversationStatus = "creating" | "reconnecting" | "ready" | "streaming" | "error";

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
  reconnect: () => void;
  startNew: () => void;
  rate: (messageId: string, rating: FeedbackRating, reason?: FeedbackReason) => void;
  clearError: () => void;
}

interface LastSend {
  content: string;
  clientMessageId: string;
}

const SESSION_KEY = "cadre_widget_session_v1";

interface StoredSession {
  conversationId: string;
  token: string;
}

function loadStoredSession(): StoredSession | null {
  try {
    const raw = window.sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredSession>;
    if (typeof parsed?.conversationId === "string" && typeof parsed?.token === "string") {
      return { conversationId: parsed.conversationId, token: parsed.token };
    }
  } catch {
    // sessionStorage blocked (privacy mode / sandboxed iframe) or bad JSON → no resume.
  }
  return null;
}

function storeSession(session: StoredSession): void {
  try {
    window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch {
    // Persistence is best-effort; the in-memory session still works this page load.
  }
}

function clearStoredSession(): void {
  try {
    window.sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // ignore
  }
}

// Deterministic id for the streaming placeholder so retries (same client_message_id)
// replace the previous failed turn instead of stacking a second one.
function placeholderId(clientMessageId: string): string {
  return `pending_${clientMessageId}`;
}

function transcriptToChatMessage(m: TranscriptMessage): ChatMessage {
  const actions: SuggestedAction[] =
    m.role === "assistant" && m.status === "completed"
      ? m.suggested_action_ids.map((id) => ({ id, label: actionLabel(id) }))
      : [];
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    status: m.status,
    suggestedActions: actions,
    sources: m.sources,
  };
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
  // Live mirror of `messages` + the completed-assistant count captured at the start of
  // the in-flight turn, so a drop-reconcile can tell whether a NEW answer landed (this
  // turn completed) versus only seeing the PRIOR turn's answer in the transcript.
  const messagesRef = useRef<ChatMessage[]>([]);
  const preTurnAssistantCountRef = useRef(0);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const applySession = useCallback((cid: string, token: string) => {
    conversationIdRef.current = cid;
    sessionTokenRef.current = token;
    setConversationId(cid);
    setSessionToken(token);
  }, []);

  // Create a brand-new conversation. `isActive` guards against a StrictMode/unmount
  // race writing state after the effect was torn down.
  const doCreateFresh = useCallback(
    async (isActive: () => boolean = () => true) => {
      setError(null);
      setStatus("creating");
      try {
        const res = await createConversation();
        if (!isActive()) return;
        applySession(res.conversation_id, res.session_token);
        storeSession({ conversationId: res.conversation_id, token: res.session_token });
        setMessages([]);
        setWelcome(res.welcome);
        setStatus("ready");
      } catch {
        if (!isActive()) return;
        // startFailed maps to a create-capable recovery action (unlike generalFailure,
        // whose only action is Retry — a no-op when no turn was ever sent).
        setError(ERROR_COPY.startFailed);
        setStatus("error");
      }
    },
    [applySession],
  );

  // Resume the stored conversation from the transcript. Returns false if there is no
  // stored session or it is truly gone (caller should create fresh).
  const resumeStored = useCallback(
    async (signal?: AbortSignal, isActive: () => boolean = () => true): Promise<boolean> => {
      const stored = loadStoredSession();
      if (!stored) return false;
      setError(null);
      setStatus("reconnecting");
      try {
        const res = await getTranscript(stored.conversationId, stored.token, signal);
        if (!isActive()) return true;
        if (res.messages.length === 0) {
          // The stored conversation is empty (reloaded before sending anything). There
          // is nothing to resume and no welcome in the transcript, so start fresh rather
          // than show a blank pane.
          clearStoredSession();
          return false;
        }
        applySession(stored.conversationId, stored.token);
        setMessages(res.messages.map(transcriptToChatMessage));
        setWelcome(null);
        setStatus("ready");
        return true;
      } catch (err) {
        if (!isActive()) return true;
        if (err instanceof ApiError && (err.status === 401 || err.status === 404)) {
          clearStoredSession(); // session truly gone → let the caller create fresh
          return false;
        }
        // Transient (offline / server blip): keep the stored session and let the user
        // retry reconnecting, so the transcript isn't discarded.
        setError(ERROR_COPY.reconnectFailed);
        setStatus("error");
        return true;
      }
    },
    [applySession],
  );

  useEffect(() => {
    // Guard against React StrictMode double-invoke creating two conversations.
    if (startedRef.current) return;
    startedRef.current = true;

    const controller = new AbortController();
    let cancelled = false;
    const isActive = () => !cancelled;

    void (async () => {
      const resumed = await resumeStored(controller.signal, isActive);
      if (!resumed && isActive()) await doCreateFresh(isActive);
    })();

    return () => {
      cancelled = true;
      // Allow a StrictMode remount (dev) to re-run boot instead of getting stuck.
      startedRef.current = false;
      controller.abort();
      abortRef.current?.abort();
    };
  }, [resumeStored, doCreateFresh]);

  // Session expired mid-use (401): the token is dead. Null the live session so the
  // composer's send guard blocks (and canSend disables it), drop any in-flight
  // streaming placeholder so no spinner is left hanging, and offer a new chat.
  const handleExpired = useCallback(() => {
    clearStoredSession();
    conversationIdRef.current = null;
    sessionTokenRef.current = null;
    setConversationId(null);
    setSessionToken(null);
    setMessages((prev) => prev.filter((m) => m.status !== "streaming"));
    setError(ERROR_COPY.sessionExpired);
    setStatus("error");
  }, []);

  // A stream dropped without a terminal event. The turn may actually have completed
  // server-side (only the SSE frame was lost), so reconcile against the transcript
  // before deciding it failed.
  const reconcileAfterDrop = useCallback(
    async (assistantId: string) => {
      const cid = conversationIdRef.current;
      const token = sessionTokenRef.current;
      // Keep the optimistic user bubble; drop an empty placeholder or mark partial text
      // failed. Never blindly replace the list from the transcript here — a not-yet-
      // persisted user message would vanish with no way to see or retry the question.
      const markFailed = () => {
        setMessages((prev) =>
          prev.flatMap((m) => {
            if (m.id !== assistantId) return [m];
            return m.content.length > 0 ? [{ ...m, status: "failed" as const }] : [];
          }),
        );
        setError(ERROR_COPY.generalFailure);
        setStatus("error");
      };
      if (!cid || !token) {
        markFailed();
        return;
      }
      setStatus("reconnecting");
      try {
        const res = await getTranscript(cid, token);
        // A turn completed iff a NEW completed-assistant message exists beyond the count
        // present before this turn — NOT merely "the last message is a completed
        // assistant" (which could be the prior turn when this turn never persisted).
        const completedAssistants = res.messages.filter(
          (m) => m.role === "assistant" && m.status === "completed",
        ).length;
        if (completedAssistants > preTurnAssistantCountRef.current) {
          // The answer landed despite the dropped frame → adopt the authoritative server
          // transcript (replaces the partial placeholder with the real reply).
          setMessages(res.messages.map(transcriptToChatMessage));
          setError(null);
          setStatus("ready");
        } else {
          // The turn did not complete server-side → keep the question visible, mark the
          // turn failed, and leave retry available (lastSendRef still holds the cmid).
          markFailed();
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          handleExpired();
        } else {
          markFailed();
        }
      }
    },
    [handleExpired],
  );

  // Runs one assistant turn. `appendUserMessage` is false on retry (the user bubble
  // already exists and we reuse the original client_message_id for idempotency).
  const runTurn = useCallback(
    (content: string, clientMessageId: string, appendUserMessage: boolean) => {
      const cid = conversationIdRef.current;
      const token = sessionTokenRef.current;
      if (!cid || !token) return;

      const assistantId = placeholderId(clientMessageId);
      lastSendRef.current = { content, clientMessageId };
      // Snapshot the completed-assistant count BEFORE this turn's optimistic append, so
      // a drop-reconcile can detect whether a new answer actually landed.
      preTurnAssistantCountRef.current = messagesRef.current.filter(
        (m) => m.role === "assistant" && m.status === "completed",
      ).length;

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
            const sources = evt.data.sources as ChatMessage["sources"] | undefined;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, id: finalId, status: "completed", suggestedActions: actions, sources }
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
          // Stream closed cleanly but with no terminal event (proxy/LB drop): the turn
          // may still have completed server-side, so reconcile from the transcript
          // instead of assuming failure.
          if (controller.signal.aborted || terminalSeen) return;
          void reconcileAfterDrop(assistantId);
        })
        .catch((err) => {
          if (controller.signal.aborted) return;
          if (err instanceof ApiError) {
            // Session expired → recover via a new chat.
            if (err.status === 401 || err.code === "UNAUTHORIZED_SESSION") {
              handleExpired();
              return;
            }
            // Pre-stream rejection: the placeholder has no text, so drop it and map copy.
            let copy: string = ERROR_COPY.generalFailure;
            if (err.code === "MESSAGE_TOO_LONG") copy = ERROR_COPY.tooLong;
            else if (err.code === "CONVERSATION_BUSY") copy = ERROR_COPY.busy;
            else if (err.code === "RETRIEVAL_UNAVAILABLE") copy = ERROR_COPY.retrieval;
            setMessages((prev) => prev.filter((m) => m.id !== assistantId));
            setError(copy);
            setStatus("error");
            return;
          }
          // A mid-stream network drop (not an ApiError) → reconcile from the transcript.
          void reconcileAfterDrop(assistantId);
        });
    },
    [reconcileAfterDrop, handleExpired],
  );

  const send = useCallback(
    (content: string) => {
      if (status === "streaming" || status === "creating" || status === "reconnecting") return;
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
    if (status === "streaming" || status === "creating" || status === "reconnecting") return;
    // Reuse the original client_message_id so the backend replays idempotently.
    runTurn(last.content, last.clientMessageId, false);
  }, [runTurn, status]);

  const reconnect = useCallback(() => {
    if (status === "streaming" || status === "reconnecting") return;
    void (async () => {
      const resumed = await resumeStored();
      if (!resumed) await doCreateFresh();
    })();
  }, [resumeStored, doCreateFresh, status]);

  const startNew = useCallback(() => {
    // Allowed mid-stream: aborting the in-flight controller makes its settle callbacks
    // no-op (they check `controller.signal.aborted`). Blocked only during a reconnect,
    // where a racing transcript fetch could clobber the fresh session. (Not blocked
    // during `creating` so the button that triggers this reset isn't disabled while it
    // holds focus — see App's focus-restore effect.)
    if (status === "reconnecting") return;
    clearStoredSession();
    lastSendRef.current = null;
    abortRef.current?.abort();
    // Reset to a neutral, session-less baseline SYNCHRONOUSLY, before awaiting the new
    // create. Otherwise a mid-stream reset leaves the aborted turn's streaming
    // placeholder visible during the round-trip (stuck "typing" dots), and — if the
    // create then fails — the composer would still send into the OLD, abandoned
    // conversation (its id/token refs would survive). Clearing here makes a failed
    // create land in the same clean, composer-disabled state as boot.
    conversationIdRef.current = null;
    sessionTokenRef.current = null;
    setConversationId(null);
    setSessionToken(null);
    setMessages([]);
    setWelcome(null);
    void doCreateFresh();
  }, [doCreateFresh, status]);

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

  // Sending requires a live session AND an idle state. Without the session check a
  // create/resume failure (refs null) would leave the composer enabled but silently
  // drop the typed message; requiring the session disables it until recovery succeeds.
  const canSend =
    (status === "ready" || status === "error") && conversationId !== null && sessionToken !== null;

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
    reconnect,
    startNew,
    rate,
    clearError,
  };
}
