// Empty-state welcome: greeting, the privacy/AI disclosure shown once at the top of
// the conversation (replacing the old persistent footer), and the initial suggested
// actions.

import { PrivacyDisclosure } from "../shell/PrivacyDisclosure";
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
      <PrivacyDisclosure />
      <p className="cadre-welcome-disclosure">{WELCOME_DISCLOSURE}</p>
      <SuggestedActions
        actions={welcome.suggested_actions}
        onSelect={onSelect}
        label="Suggested topics"
      />
    </div>
  );
}
