// Presentational composition of the conversation view. All state comes in as props
// (see useConversation for the source). The parent decides what selecting an action
// does, so this component just forwards onSelectAction(action).

import type { CSSProperties } from "react";

import type { ChatMessage, FeedbackRating, FeedbackReason, SuggestedAction, WelcomePayload } from "../types";
import { Composer } from "./Composer";
import { ERROR_COPY } from "./copy";
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
  onRate: (messageId: string, rating: FeedbackRating, reason?: FeedbackReason) => void;
  onDismissError: () => void;
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
  onRate,
  onDismissError,
}: ConversationViewProps) {
  const isEmpty = messages.length === 0;

  // Retry only makes sense for transient failures — not the cap or an over-long message.
  const showRetry =
    status === "error" && error !== ERROR_COPY.cap && error !== ERROR_COPY.tooLong;

  // Polite live region for streaming/creating status. Errors are announced by the
  // ErrorBanner's own role="status", so they are not duplicated here.
  const liveMessage =
    status === "streaming" ? "Generating response." : status === "creating" ? "Starting chat." : "";

  return (
    <div className="cadre-conversation">
      <div style={srOnly} role="status" aria-live="polite">
        {liveMessage}
      </div>

      <div className="cadre-conversation-scroll">
        {isEmpty && welcome && <WelcomeChips welcome={welcome} onSelect={onSelectAction} />}
        {isEmpty && !welcome && status === "creating" && (
          <p className="cadre-loading">Starting chat…</p>
        )}
        <MessageList messages={messages} onSelectAction={onSelectAction} onRate={onRate} />
      </div>

      {error && (
        <ErrorBanner
          error={error}
          onRetry={showRetry ? onRetry : undefined}
          onDismiss={onDismissError}
        />
      )}

      <Composer
        onSend={onSend}
        disabled={!canSend}
        placeholder="Ask about strategy, portal access, or contacting Cadre"
      />
    </div>
  );
}
