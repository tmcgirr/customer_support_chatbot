// Small, self-contained validation + display helpers for the request forms.
// No external deps: a pragmatic email regex and an email masking helper live here
// (the widget never depends on a validation library).

import type { Contact, RequestType, SubmitRequestPayload } from "../types";
import { CONSENT_VERSION } from "../config";

// Pragmatic email check: one "@", non-empty local part, a dotted domain, no spaces.
// Intentionally lenient — the backend performs authoritative validation.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isValidEmail(email: string): boolean {
  return EMAIL_RE.test(email.trim());
}

/**
 * Mask an email for the review screen, e.g. "ada@acme.com" -> "a***@acme.com".
 * Falls back to the raw value if it doesn't look like an email (shouldn't happen
 * for values that passed validation).
 */
export function maskEmail(email: string): string {
  const trimmed = email.trim();
  const at = trimmed.indexOf("@");
  if (at <= 0) return trimmed;
  const local = trimmed.slice(0, at);
  const domain = trimmed.slice(at + 1);
  return `${local[0]}***@${domain}`;
}

// The mutable draft the form edits. All fields are strings so inputs stay
// controlled; per-type payloads are assembled from the relevant subset.
export interface RequestDraft {
  // contact
  name: string;
  email: string;
  company: string;
  // strategy_call
  reason: string;
  industry: string;
  region: string;
  // portal_support
  issue_category: "forgot_password" | "no_access" | "error" | "other";
  description: string;
  error_message: string;
  steps_attempted: string;
  // human_escalation
  category: string;
  original_question: string;
  context_summary: string;
}

export function emptyDraft(originalQuestion?: string): RequestDraft {
  return {
    name: "",
    email: "",
    company: "",
    reason: "",
    industry: "",
    region: "",
    issue_category: "forgot_password",
    description: "",
    error_message: "",
    steps_attempted: "",
    category: "",
    original_question: originalQuestion ?? "",
    context_summary: "",
  };
}

export type FieldErrors = Partial<Record<keyof RequestDraft, string>>;

/**
 * Validate the draft for the given type. Returns a map of field -> message for
 * every field that fails; an empty object means the draft may advance to review.
 */
export function validateDraft(type: RequestType, draft: RequestDraft): FieldErrors {
  const errors: FieldErrors = {};
  const req = (value: string) => value.trim().length > 0;

  if (type === "strategy_call") {
    if (!req(draft.name)) errors.name = "Please enter your name.";
    if (!req(draft.email)) errors.email = "Please enter your work email.";
    else if (!isValidEmail(draft.email)) errors.email = "Please enter a valid email address.";
    if (!req(draft.company)) errors.company = "Please enter your company.";
    if (!req(draft.reason)) errors.reason = "Please describe what you'd like to discuss.";
  } else if (type === "portal_support") {
    if (!req(draft.name)) errors.name = "Please enter your name.";
    if (!req(draft.email)) errors.email = "Please enter your work email.";
    else if (!isValidEmail(draft.email)) errors.email = "Please enter a valid email address.";
    if (!req(draft.company)) errors.company = "Please enter your company.";
    if (!req(draft.description)) errors.description = "Please describe the issue.";
  } else {
    // human_escalation: contact is optional, but if an email is given it must be valid.
    if (req(draft.email) && !isValidEmail(draft.email))
      errors.email = "Please enter a valid email address.";
    // Only the question is required (category + summary optional), matching the
    // backend — someone who just wants a person isn't blocked on filler text.
    if (!req(draft.original_question)) errors.original_question = "Please include your question.";
  }

  return errors;
}

// Build the contact object, omitting empty fields (human_escalation may submit
// an entirely empty contact).
function buildContact(draft: RequestDraft): Contact {
  const contact: Contact = {};
  if (draft.name.trim()) contact.name = draft.name.trim();
  if (draft.email.trim()) contact.email = draft.email.trim();
  if (draft.company.trim()) contact.company = draft.company.trim();
  return contact;
}

// Build the per-type `fields` object, including only provided optional fields.
function buildFields(type: RequestType, draft: RequestDraft): Record<string, unknown> {
  const withOptional = (
    base: Record<string, unknown>,
    optionals: Record<string, string>,
  ): Record<string, unknown> => {
    const out = { ...base };
    for (const [key, value] of Object.entries(optionals)) {
      if (value.trim()) out[key] = value.trim();
    }
    return out;
  };

  if (type === "strategy_call") {
    return withOptional(
      { reason: draft.reason.trim() },
      { industry: draft.industry, region: draft.region },
    );
  }
  if (type === "portal_support") {
    return withOptional(
      { issue_category: draft.issue_category, description: draft.description.trim() },
      { error_message: draft.error_message, steps_attempted: draft.steps_attempted },
    );
  }
  return {
    category: draft.category.trim(),
    original_question: draft.original_question.trim(),
    context_summary: draft.context_summary.trim(),
  };
}

export function buildPayload(
  type: RequestType,
  conversationId: string,
  draft: RequestDraft,
): SubmitRequestPayload {
  return {
    type,
    conversation_id: conversationId,
    contact: buildContact(draft),
    fields: buildFields(type, draft),
    consent_version: CONSENT_VERSION,
    confirmed: true,
  };
}
