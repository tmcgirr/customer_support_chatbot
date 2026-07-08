import { useId, useMemo, useRef, useState } from "react";

import { ApiError, newClientMessageId, submitRequest } from "../api/client";
import type { RequestType } from "../types";
import {
  buildPayload,
  emptyDraft,
  maskEmail,
  validateDraft,
  type FieldErrors,
  type RequestDraft,
} from "./validation";
import "./RequestForm.css";

export interface RequestFormProps {
  type: RequestType;
  conversationId: string;
  token: string;
  originalQuestion?: string;
  onClose: () => void;
  onSubmitted: (reference: string) => void;
}

type Step = "edit" | "review" | "success" | "failure" | "duplicate";

const CONSENT_STATEMENT =
  "By submitting this request, you agree that Cadre may use the information provided to " +
  "respond to your inquiry and manage the related customer workflow.";

const ENTRY_HELP: Partial<Record<RequestType, string>> = {
  strategy_call:
    "I can help you request a conversation with an AI strategist — I'll open a short form " +
    "so the request reaches the right team.",
  human_escalation:
    "I can send your request to the appropriate Cadre team — I'll collect the minimum " +
    "information needed for follow-up, and I'll include the relevant context so you don't " +
    "have to repeat the question.",
};

const TITLES: Record<RequestType, string> = {
  strategy_call: "Request a strategy call",
  portal_support: "Client portal support",
  human_escalation: "Contact the Cadre team",
};

const ISSUE_CATEGORY_LABELS: Record<RequestDraft["issue_category"], string> = {
  forgot_password: "Forgot password",
  no_access: "No access",
  error: "Seeing an error",
  other: "Other",
};

// Read a reference off a duplicate ApiError if the backend attached one; the
// error contract doesn't guarantee it, so this is best-effort.
function referenceFromError(err: ApiError): string | undefined {
  const maybe = err as unknown as { reference?: unknown };
  return typeof maybe.reference === "string" && maybe.reference ? maybe.reference : undefined;
}

export default function RequestForm({
  type,
  conversationId,
  token,
  originalQuestion,
  onClose,
  onSubmitted,
}: RequestFormProps) {
  const baseId = useId();
  const [draft, setDraft] = useState<RequestDraft>(() => emptyDraft(originalQuestion));
  const [step, setStep] = useState<Step>("edit");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [consent, setConsent] = useState(false);
  const [consentError, setConsentError] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [reference, setReference] = useState<string | undefined>(undefined);
  // One idempotency key per submission — minted when entering review and REUSED
  // across retries so a resubmit dedupes server-side instead of double-creating.
  const idempotencyKeyRef = useRef<string | null>(null);

  const fieldId = (name: keyof RequestDraft) => `${baseId}-${name}`;
  const errorId = (name: keyof RequestDraft) => `${baseId}-${name}-error`;

  const set = (name: keyof RequestDraft, value: string) =>
    setDraft((prev) => ({ ...prev, [name]: value }));

  const reviewRows = useMemo(() => buildReviewRows(type, draft), [type, draft]);

  function goToReview() {
    const found = validateDraft(type, draft);
    setErrors(found);
    if (Object.keys(found).length === 0) {
      setConsentError(false);
      idempotencyKeyRef.current = newClientMessageId();
      setStep("review");
    }
  }

  async function handleConfirm() {
    if (!consent) {
      setConsentError(true);
      return;
    }
    setConsentError(false);
    setSubmitting(true);
    try {
      const payload = buildPayload(type, conversationId, draft);
      const idempotencyKey = idempotencyKeyRef.current ?? newClientMessageId();
      idempotencyKeyRef.current = idempotencyKey;
      const response = await submitRequest(token, payload, idempotencyKey);
      setReference(response.reference);
      setStep("success");
      onSubmitted(response.reference);
    } catch (err) {
      if (err instanceof ApiError && (err.code === "DUPLICATE_ACTION" || err.status === 409)) {
        setReference(referenceFromError(err));
        setStep("duplicate");
      } else {
        // Non-duplicate failure: preserve the draft so the user can retry.
        setStep("failure");
      }
    } finally {
      setSubmitting(false);
    }
  }

  // --- Field rendering -----------------------------------------------------

  const textField = (
    name: keyof RequestDraft,
    label: string,
    opts: { type?: string; multiline?: boolean; optional?: boolean; autoComplete?: string } = {},
  ) => {
    const error = errors[name];
    const describedBy = error ? errorId(name) : undefined;
    const commonProps = {
      id: fieldId(name),
      value: draft[name] as string,
      "aria-invalid": error ? (true as const) : undefined,
      "aria-describedby": describedBy,
      onChange: (
        e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
      ) => set(name, e.target.value),
    };
    return (
      <div className="rf-field" key={name}>
        <label htmlFor={fieldId(name)}>
          {label}
          {opts.optional ? <span className="rf-optional"> (optional)</span> : null}
        </label>
        {opts.multiline ? (
          <textarea {...commonProps} rows={3} />
        ) : (
          <input
            {...commonProps}
            type={opts.type ?? "text"}
            autoComplete={opts.autoComplete}
          />
        )}
        {error ? (
          <span className="rf-error" id={errorId(name)} role="alert">
            {error}
          </span>
        ) : null}
      </div>
    );
  };

  const issueCategoryField = () => {
    const name: keyof RequestDraft = "issue_category";
    return (
      <div className="rf-field" key={name}>
        <label htmlFor={fieldId(name)}>Issue category</label>
        <select
          id={fieldId(name)}
          value={draft.issue_category}
          onChange={(e) => set(name, e.target.value)}
        >
          {(Object.keys(ISSUE_CATEGORY_LABELS) as RequestDraft["issue_category"][]).map((key) => (
            <option key={key} value={key}>
              {ISSUE_CATEGORY_LABELS[key]}
            </option>
          ))}
        </select>
      </div>
    );
  };

  function renderEditFields() {
    if (type === "strategy_call") {
      return (
        <>
          {textField("name", "Name", { autoComplete: "name" })}
          {textField("email", "Work email", { type: "email", autoComplete: "email" })}
          {textField("company", "Company", { autoComplete: "organization" })}
          {textField("reason", "What would you like to discuss?", { multiline: true })}
          {textField("industry", "Industry", { optional: true })}
          {textField("region", "Region", { optional: true })}
        </>
      );
    }
    if (type === "portal_support") {
      return (
        <>
          {textField("name", "Name", { autoComplete: "name" })}
          {textField("email", "Work email", { type: "email", autoComplete: "email" })}
          {textField("company", "Company", { autoComplete: "organization" })}
          {issueCategoryField()}
          {textField("description", "Describe the issue", { multiline: true })}
          {textField("error_message", "Error message you saw", { optional: true, multiline: true })}
          {textField("steps_attempted", "Steps you already tried", {
            optional: true,
            multiline: true,
          })}
        </>
      );
    }
    // human_escalation
    return (
      <>
        {textField("category", "What is this about?")}
        {textField("original_question", "Your question", { multiline: true })}
        {textField("context_summary", "Anything else that would help", { multiline: true })}
        <p className="rf-subhead">Contact details (optional)</p>
        {textField("name", "Name", { optional: true, autoComplete: "name" })}
        {textField("email", "Email", { optional: true, type: "email", autoComplete: "email" })}
        {textField("company", "Company", { optional: true, autoComplete: "organization" })}
      </>
    );
  }

  // --- Steps ---------------------------------------------------------------

  const headingId = `${baseId}-heading`;

  const shell = (children: React.ReactNode) => (
    <section className="rf-root" role="group" aria-labelledby={headingId}>
      <h2 id={headingId} className="rf-title">
        {TITLES[type]}
      </h2>
      {children}
    </section>
  );

  if (step === "edit") {
    return shell(
      <form
        className="rf-form"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          goToReview();
        }}
      >
        {ENTRY_HELP[type] ? <p className="rf-help">{ENTRY_HELP[type]}</p> : null}
        {type === "portal_support" ? (
          <p className="rf-warning" role="note">
            Please do not share your password or authentication code.
          </p>
        ) : null}
        {renderEditFields()}
        <div className="rf-actions">
          <button type="button" className="rf-btn rf-btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="rf-btn rf-btn-primary">
            Review
          </button>
        </div>
      </form>,
    );
  }

  if (step === "review") {
    const consentBoxId = `${baseId}-consent`;
    return shell(
      <div className="rf-review">
        <p className="rf-help">Please review your request before submitting.</p>
        <dl className="rf-summary">
          {reviewRows.map((row) => (
            <div className="rf-summary-row" key={row.label}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
        <p className="rf-consent-statement">{CONSENT_STATEMENT}</p>
        <div className="rf-field rf-consent">
          <input
            id={consentBoxId}
            type="checkbox"
            checked={consent}
            aria-describedby={consentError ? `${baseId}-consent-error` : undefined}
            aria-invalid={consentError ? true : undefined}
            onChange={(e) => {
              setConsent(e.target.checked);
              if (e.target.checked) setConsentError(false);
            }}
          />
          <label htmlFor={consentBoxId}>
            I have read and agree to the statement above.
          </label>
        </div>
        {consentError ? (
          <span className="rf-error" id={`${baseId}-consent-error`} role="alert">
            Please confirm consent before submitting.
          </span>
        ) : null}
        <div className="rf-actions">
          <button
            type="button"
            className="rf-btn rf-btn-ghost"
            onClick={() => setStep("edit")}
            disabled={submitting}
          >
            Edit
          </button>
          <button
            type="button"
            className="rf-btn rf-btn-ghost"
            onClick={onClose}
            disabled={submitting}
          >
            Cancel
          </button>
          <button
            type="button"
            className="rf-btn rf-btn-primary"
            onClick={handleConfirm}
            disabled={submitting}
          >
            {submitting ? "Submitting…" : "Submit request"}
          </button>
        </div>
      </div>,
    );
  }

  if (step === "success") {
    return shell(
      <div className="rf-result">
        <p className="rf-success" role="status">
          Your request has been submitted. Reference: {reference}.
        </p>
        <div className="rf-actions">
          <button type="button" className="rf-btn rf-btn-primary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>,
    );
  }

  if (step === "duplicate") {
    return shell(
      <div className="rf-result">
        <p className="rf-notice" role="status">
          This request appears to have already been submitted.
          {reference ? ` Reference: ${reference}.` : ""}
        </p>
        <div className="rf-actions">
          <button type="button" className="rf-btn rf-btn-primary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>,
    );
  }

  // step === "failure" — draft is preserved; return to review to retry.
  return shell(
    <div className="rf-result">
      <p className="rf-error-banner" role="alert">
        Your request was not submitted. Your information is still here so you can retry or use the
        contact option below.
      </p>
      <div className="rf-actions">
        <button type="button" className="rf-btn rf-btn-ghost" onClick={onClose}>
          Close
        </button>
        <button
          type="button"
          className="rf-btn rf-btn-primary"
          onClick={() => setStep("review")}
        >
          Try again
        </button>
      </div>
    </div>,
  );
}

interface ReviewRow {
  label: string;
  value: string;
}

function buildReviewRows(type: RequestType, draft: RequestDraft): ReviewRow[] {
  const rows: ReviewRow[] = [];
  const push = (label: string, value: string) => {
    if (value.trim()) rows.push({ label, value: value.trim() });
  };

  if (type === "human_escalation") {
    push("What is this about?", draft.category);
    push("Your question", draft.original_question);
    push("Additional context", draft.context_summary);
    push("Name", draft.name);
    if (draft.email.trim()) rows.push({ label: "Email", value: maskEmail(draft.email) });
    push("Company", draft.company);
    return rows;
  }

  push("Name", draft.name);
  if (draft.email.trim()) rows.push({ label: "Email", value: maskEmail(draft.email) });
  push("Company", draft.company);

  if (type === "strategy_call") {
    push("Reason", draft.reason);
    push("Industry", draft.industry);
    push("Region", draft.region);
  } else {
    rows.push({ label: "Issue category", value: ISSUE_CATEGORY_LABELS[draft.issue_category] });
    push("Description", draft.description);
    push("Error message", draft.error_message);
    push("Steps attempted", draft.steps_attempted);
  }
  return rows;
}
