// Empty-state welcome: greeting, AI disclosure, and the initial suggested actions.

import type { SuggestedAction, WelcomePayload } from "../types";
import { WELCOME_DISCLOSURE } from "./copy";
import { SuggestedActions } from "./SuggestedActions";

interface WelcomeChipsProps {
  welcome: WelcomePayload;
  onSelect: (action: SuggestedAction) => void;
}

export function WelcomeChips({ welcome, onSelect }: WelcomeChipsProps) {
  return (
    <div className="cadre-welcome">
      <p className="cadre-welcome-text">{welcome.text}</p>
      <p className="cadre-welcome-disclosure">{WELCOME_DISCLOSURE}</p>
      <SuggestedActions
        actions={welcome.suggested_actions}
        onSelect={onSelect}
        label="Suggested topics"
      />
    </div>
  );
}
