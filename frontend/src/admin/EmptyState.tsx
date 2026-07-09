import type { ReactNode } from "react";

import { Icon } from "./icons";

/** A structured placeholder for empty views — icon + title + hint + optional action.
 *  Replaces bare lines of muted text so "no data yet" states read as intentional. */
export default function EmptyState({
  icon = "insights",
  title,
  hint,
  action,
}: {
  icon?: string;
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="admin-empty">
      <span className="admin-empty-icon">
        <Icon name={icon} size={26} />
      </span>
      <span className="admin-empty-title">{title}</span>
      {hint && <p className="admin-empty-hint">{hint}</p>}
      {action && <div className="admin-empty-action">{action}</div>}
    </div>
  );
}
