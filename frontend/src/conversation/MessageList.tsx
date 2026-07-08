// Ordered list of message bubbles. Binds each message id to the rate callback.

import type { ChatMessage, FeedbackRating, FeedbackReason, SuggestedAction } from "../types";
import { ChatMessageItem } from "./ChatMessageItem";

interface MessageListProps {
  messages: ChatMessage[];
  onSelectAction: (action: SuggestedAction) => void;
  onRate: (messageId: string, rating: FeedbackRating, reason?: FeedbackReason) => void;
}

export function MessageList({ messages, onSelectAction, onRate }: MessageListProps) {
  return (
    <ol className="cadre-message-list">
      {messages.map((message) => (
        <li key={message.id} className="cadre-message-list-item">
          <ChatMessageItem
            message={message}
            onSelectAction={onSelectAction}
            onRate={(rating, reason) => onRate(message.id, rating, reason)}
          />
        </li>
      ))}
    </ol>
  );
}
