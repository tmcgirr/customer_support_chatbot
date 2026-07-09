import { useEffect, useRef, useState } from "react";

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
  // Open by default for now (dev/demo convenience); flip back to false to ship the
  // launcher-first behavior.
  const [open, setOpen] = useState(true);
  const [formType, setFormType] = useState<RequestType | null>(null);
  const [originalQuestion, setOriginalQuestion] = useState<string | undefined>(undefined);
  const conversation = useConversation();
  // Focused by WidgetFrame when the panel opens so the user can type immediately.
  const composerRef = useRef<HTMLTextAreaElement>(null);
  // Set when the user starts a new chat, so focus can be returned to the composer of
  // the fresh conversation once it is ready (the New-chat button that had focus is
  // otherwise left behind / momentarily disabled).
  const pendingNewChatFocus = useRef(false);

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

  // Start a fresh conversation: close any open form and reset to a brand-new thread
  // with an empty transcript (like a first-time visitor).
  function handleNewChat(): void {
    setFormType(null);
    setOriginalQuestion(undefined);
    pendingNewChatFocus.current = true;
    conversation.startNew();
  }

  // Once the fresh chat settles to ready, move focus into its composer. This restores
  // focus after the New-chat button (which had it) — the composer is disabled during
  // the brief "creating" phase, so we wait for ready.
  useEffect(() => {
    if (pendingNewChatFocus.current && conversation.status === "ready") {
      pendingNewChatFocus.current = false;
      composerRef.current?.focus();
    }
  }, [conversation.status]);

  // New chat is unavailable only while reconnecting (a racing resume could clobber the
  // fresh session). It stays enabled during its own "creating" so the button that
  // triggered it isn't disabled while focused.
  const canStartNew = conversation.status !== "reconnecting";

  return (
    <WidgetFrame
      open={open}
      onToggle={() => setOpen((value) => !value)}
      onClose={() => setOpen(false)}
      onNewChat={handleNewChat}
      canStartNew={canStartNew}
      initialFocusRef={composerRef}
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
          composerRef={composerRef}
          welcome={conversation.welcome}
          messages={conversation.messages}
          status={conversation.status}
          error={conversation.error}
          canSend={conversation.canSend}
          onSend={conversation.send}
          onSelectAction={handleSelectAction}
          onRetry={conversation.retryLast}
          onReconnect={conversation.reconnect}
          onStartNew={conversation.startNew}
          onRate={conversation.rate}
          onDismissError={conversation.clearError}
        />
      )}
    </WidgetFrame>
  );
}
