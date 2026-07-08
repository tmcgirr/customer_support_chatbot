// "Was this helpful?" control. Thumbs up submits immediately; thumbs down reveals the
// negative reasons, and picking one submits. Either path ends on an acknowledgement.

import { useId, useState } from "react";

import type { FeedbackRating, FeedbackReason } from "../types";
import { FEEDBACK_ACK, FEEDBACK_PROMPT, FEEDBACK_REASONS } from "./copy";

interface FeedbackControlProps {
  onRate: (rating: FeedbackRating, reason?: FeedbackReason) => void;
}

type Phase = "prompt" | "reasons" | "done";

export function FeedbackControl({ onRate }: FeedbackControlProps) {
  const [phase, setPhase] = useState<Phase>("prompt");
  const promptId = useId();

  if (phase === "done") {
    return (
      <p className="cadre-feedback-ack" role="status">
        {FEEDBACK_ACK}
      </p>
    );
  }

  if (phase === "reasons") {
    return (
      <div className="cadre-feedback-reasons" role="group" aria-label="What went wrong?">
        {FEEDBACK_REASONS.map((reason) => (
          <button
            key={reason.value}
            type="button"
            className="cadre-chip"
            onClick={() => {
              onRate("not_helpful", reason.value);
              setPhase("done");
            }}
          >
            {reason.label}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className="cadre-feedback" role="group" aria-labelledby={promptId}>
      <span id={promptId} className="cadre-feedback-prompt">
        {FEEDBACK_PROMPT}
      </span>
      <button
        type="button"
        className="cadre-feedback-thumb"
        aria-label="Yes, this was helpful"
        onClick={() => {
          onRate("helpful");
          setPhase("done");
        }}
      >
        <span aria-hidden="true">&#128077;</span>
      </button>
      <button
        type="button"
        className="cadre-feedback-thumb"
        aria-label="No, this was not helpful"
        onClick={() => setPhase("reasons")}
      >
        <span aria-hidden="true">&#128078;</span>
      </button>
    </div>
  );
}
