import { useState } from "react";

import { ConversationView, useConversation } from "./conversation";
import RequestForm from "./forms/RequestForm";
import { WidgetFrame } from "./shell/WidgetFrame";
import type { RequestType, SuggestedAction } from "./types";

// Suggested-action IDs that open a structured form (side effects go through the
// browser, never the model — ADR-016). Everything else is sent as a message.
const ACTION_TO_FORM: Record<string, RequestType> = {
  strategy_call: "strategy_call",
  portal_support: "portal_support",
  human_escalation: "human_escalation",
};

export default function App() {
  const [open, setOpen] = useState(false);
  const [formType, setFormType] = useState<RequestType | null>(null);
  const [originalQuestion, setOriginalQuestion] = useState<string | undefined>(undefined);
  const conversation = useConversation();

  function handleSelectAction(action: SuggestedAction): void {
    const form = ACTION_TO_FORM[action.id];
    if (!form) {
      conversation.send(action.label);
      return;
    }
    if (form === "human_escalation") {
      const lastUser = [...conversation.messages].reverse().find((m) => m.role === "user");
      setOriginalQuestion(lastUser?.content);
    }
    setFormType(form);
  }

  return (
    <WidgetFrame
      open={open}
      onToggle={() => setOpen((value) => !value)}
      onClose={() => setOpen(false)}
    >
      {formType && conversation.conversationId && conversation.sessionToken ? (
        <RequestForm
          type={formType}
          conversationId={conversation.conversationId}
          token={conversation.sessionToken}
          originalQuestion={originalQuestion}
          onClose={() => setFormType(null)}
          onSubmitted={() => undefined}
        />
      ) : (
        <ConversationView
          welcome={conversation.welcome}
          messages={conversation.messages}
          status={conversation.status}
          error={conversation.error}
          canSend={conversation.canSend}
          onSend={conversation.send}
          onSelectAction={handleSelectAction}
          onRetry={conversation.retryLast}
          onRate={conversation.rate}
          onDismissError={conversation.clearError}
        />
      )}
    </WidgetFrame>
  );
}
