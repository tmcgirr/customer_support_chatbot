// Presentational composition of the conversation view. All state comes in as props
// (see useConversation for the source). The parent decides what selecting an action
// does, so this component just forwards onSelectAction(action).

import { useEffect, useRef, useState } from "react";
import type { CSSProperties, RefObject } from "react";

import type { ChatMessage, FeedbackRating, FeedbackReason, SuggestedAction, WelcomePayload } from "../types";
import { Composer } from "./Composer";
import { ERROR_COPY, RECONNECTING_STATUS, STREAM_STATUS } from "./copy";
import type { ErrorAction } from "./ErrorBanner";
import { ErrorBanner } from "./ErrorBanner";
import { MessageList } from "./MessageList";
import type { ConversationStatus } from "./useConversation";
import { WelcomeChips } from "./WelcomeChips";

// Screen-reader-only, applied inline so hiding does not depend on external CSS.
const srOnly: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0 0 0 0)",
  whiteSpace: "nowrap",
  border: 0,
};

export interface ConversationViewProps {
  welcome: WelcomePayload | null;
  messages: ChatMessage[];
  status: ConversationStatus;
  error: string | null;
  canSend: boolean;
  onSend: (content: string) => void;
  onSelectAction: (action: SuggestedAction) => void;
  onRetry: () => void;
  onReconnect: () => void;
  onStartNew: () => void;
  onRate: (messageId: string, rating: FeedbackRating, reason?: FeedbackReason) => void;
  onDismissError: () => void;
  /** Focused when the panel opens (see WidgetFrame.initialFocusRef). */
  composerRef?: RefObject<HTMLTextAreaElement>;
}

export function ConversationView({
  welcome,
  messages,
  status,
  error,
  canSend,
  onSend,
  onSelectAction,
  onRetry,
  onReconnect,
  onStartNew,
  onRate,
  onDismissError,
  composerRef,
}: ConversationViewProps) {
  const isEmpty = messages.length === 0;

  // Polite status live region. It announces process transitions only (not message
  // text — the log region below carries that): a turn STARTING ("Assistant is
  // responding…") AND FINISHING ("Response complete." / failed), plus creating and
  // reconnecting. Driven by an effect that compares against the previous status so a
  // screen reader hears both the start and the end of a streamed turn.
  const [liveAnnouncement, setLiveAnnouncement] = useState("");
  const prevStatusRef = useRef<ConversationStatus>(status);

  useEffect(() => {
    const prev = prevStatusRef.current;
    prevStatusRef.current = status;
    switch (status) {
      case "streaming":
        setLiveAnnouncement(STREAM_STATUS.thinking);
        break;
      case "reconnecting":
        setLiveAnnouncement(RECONNECTING_STATUS);
        break;
      case "creating":
        setLiveAnnouncement("Starting chat.");
        break;
      case "ready":
        // Only announce completion for a turn that was actively streaming; a plain
        // create/reconnect settling to ready stays silent.
        setLiveAnnouncement(prev === "streaming" ? STREAM_STATUS.done : "");
        break;
      case "error":
        // Announce a streamed turn's failure here; other errors are voiced by the
        // ErrorBanner's own role="status" so they are not duplicated.
        setLiveAnnouncement(prev === "streaming" ? STREAM_STATUS.failed : "");
        break;
    }
  }, [status]);

  // Which recovery actions the error banner offers depends on the degraded state.
  let errorActions: ErrorAction[] = [];
  if (status === "error" && error) {
    if (error === ERROR_COPY.sessionExpired) {
      errorActions = [{ label: "Start new chat", onClick: onStartNew }];
    } else if (error === ERROR_COPY.startFailed) {
      // Initial create failed → the only useful recovery is to try creating again.
      errorActions = [{ label: "Try again", onClick: onStartNew }];
    } else if (error === ERROR_COPY.reconnectFailed) {
      errorActions = [
        { label: "Reconnect", onClick: onReconnect },
        { label: "Start new chat", onClick: onStartNew },
      ];
    } else if (error !== ERROR_COPY.cap && error !== ERROR_COPY.tooLong) {
      // Transient generation failure — retry the last turn.
      errorActions = [{ label: "Retry", onClick: onRetry }];
    }
  }

  return (
    <div className="cadre-conversation">
      <div style={srOnly} role="status" aria-live="polite" aria-atomic="true">
        {liveAnnouncement}
      </div>

      {/* Message transcript as a log: new messages are announced politely, but only
          node ADDITIONS (a new bubble) — not token-by-token text mutations of the
          streaming bubble, so partial text never spams the screen reader. */}
      <div
        className="cadre-conversation-scroll"
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="Conversation"
      >
        {isEmpty && welcome && <WelcomeChips welcome={welcome} onSelect={onSelectAction} />}
        {isEmpty && !welcome && status === "creating" && (
          <p className="cadre-loading">Starting chat…</p>
        )}
        {isEmpty && status === "reconnecting" && (
          <p className="cadre-loading">{RECONNECTING_STATUS}</p>
        )}
        <MessageList messages={messages} onSelectAction={onSelectAction} onRate={onRate} />
      </div>

      {error && (
        <ErrorBanner error={error} actions={errorActions} onDismiss={onDismissError} />
      )}

      <Composer
        inputRef={composerRef}
        onSend={onSend}
        disabled={!canSend}
        placeholder="Ask about strategy, portal access, or contacting Cadre"
      />
    </div>
  );
}
