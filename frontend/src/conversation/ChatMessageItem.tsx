// A single message bubble. Assistant turns show a typing indicator while streaming,
// an "incomplete" note when failed/partial, and suggested actions + feedback once
// completed. The message text lives in its own element (no child elements) so tests
// and screen readers read it cleanly.

import type { ChatMessage, FeedbackRating, FeedbackReason, SuggestedAction } from "../types";
import { FeedbackControl } from "./FeedbackControl";
import { SuggestedActions } from "./SuggestedActions";

interface ChatMessageItemProps {
  message: ChatMessage;
  onSelectAction: (action: SuggestedAction) => void;
  onRate: (rating: FeedbackRating, reason?: FeedbackReason) => void;
}

export function ChatMessageItem({ message, onSelectAction, onRate }: ChatMessageItemProps) {
  const isAssistant = message.role === "assistant";
  const isStreaming = message.status === "streaming";
  const isIncomplete = message.status === "failed" || message.status === "partial";

  return (
    <div
      className={`cadre-message cadre-message-${message.role}`}
      data-status={message.status}
    >
      <div className="cadre-message-body">
        {/* Speaker label as real (visually-hidden) text so it is spoken with the
            message when the log region announces the new bubble. aria-label on this
            generic <div> would be ignored by the log announcement and is prohibited
            on a role-less element, so a sr-only span is used instead. */}
        <span className="cadre-sr-only">{isAssistant ? "Assistant said: " : "You said: "}</span>
        <span className="cadre-message-text">{message.content}</span>
        {isStreaming && (
          <span className="cadre-typing" aria-hidden="true">
            &#8226;&#8226;&#8226;
          </span>
        )}
      </div>

      {isIncomplete && <p className="cadre-message-incomplete">Response incomplete.</p>}

      {isAssistant && message.status === "completed" && message.sources
        && message.sources.length > 0 && (
        <nav className="cadre-citations" aria-label="Sources">
          <p className="cadre-citations-label">Sources</p>
          <ul>
            {message.sources.map((source, i) => (
              <li key={`${source.url}-${i}`}>
                <a href={source.url} target="_blank" rel="noopener noreferrer">
                  {source.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      )}

      {isAssistant && message.status === "completed" && (
        <>
          <SuggestedActions actions={message.suggestedActions} onSelect={onSelectAction} />
          <FeedbackControl onRate={onRate} />
        </>
      )}
    </div>
  );
}
