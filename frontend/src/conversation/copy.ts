// User-facing copy for the conversation view. Strings are verbatim from
// docs/05_Conversation_and_Content_Specification.md (§6 errors, feedback, welcome).
// Keep these in one place so the hook and the presentational components stay in sync.

import type { FeedbackReason } from "../types";

export const ERROR_COPY = {
  generalFailure:
    "I'm having trouble generating a response right now. You can try again or contact Cadre directly.",
  retrieval:
    "Detailed knowledge search is temporarily unavailable. I can still help with common questions, portal access, or contacting Cadre.",
  busy: "Please wait for the current response to complete.",
  cap: "You've reached the current chat limit. You can still contact Cadre through the options below.",
  tooLong:
    "That message is longer than the chat currently supports. Please shorten it or use the contact form.",
} as const;

// Supporting disclosure shown on the welcome / empty state (docs/05 §opening disclosure).
export const WELCOME_DISCLOSURE =
  "This assistant uses AI and may not have every answer. You can ask to speak with a person at any time.";

// Feedback acknowledgement (docs/05 §feedback).
export const FEEDBACK_ACK = "Thank you. Your feedback will help Cadre improve the assistant.";

export const FEEDBACK_PROMPT = "Was this helpful?";

// Negative feedback reasons. Values match the FeedbackReason union in types.ts.
export const FEEDBACK_REASONS: ReadonlyArray<{ value: FeedbackReason; label: string }> = [
  { value: "incorrect", label: "Incorrect" },
  { value: "unclear", label: "Unclear" },
  { value: "did_not_answer", label: "Did not answer" },
  { value: "need_person", label: "Need a person" },
  { value: "other", label: "Other" },
];

// Client-side guard; the server enforces the real limit (docs/05 §6 too-long).
export const MAX_MESSAGE_LENGTH = 2000;
