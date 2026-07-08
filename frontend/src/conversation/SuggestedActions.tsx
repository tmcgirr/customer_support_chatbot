// Renders a row of suggested-action chips. Purely presentational: the parent decides
// what selecting an action does (send a message vs. open a form).

import type { SuggestedAction } from "../types";

interface SuggestedActionsProps {
  actions: SuggestedAction[];
  onSelect: (action: SuggestedAction) => void;
  label?: string;
}

export function SuggestedActions({ actions, onSelect, label }: SuggestedActionsProps) {
  if (actions.length === 0) return null;
  return (
    <div className="cadre-suggested-actions" role="group" aria-label={label ?? "Suggested actions"}>
      {actions.map((action) => (
        <button
          key={action.id}
          type="button"
          className="cadre-chip"
          onClick={() => onSelect(action)}
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}
