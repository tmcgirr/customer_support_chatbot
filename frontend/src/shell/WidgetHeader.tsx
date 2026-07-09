import { SettingsMenu } from "./SettingsMenu";
import type { A11yPrefs } from "./useAccessibilityPrefs";

export interface WidgetHeaderProps {
  /** Close the chat panel. */
  onClose: () => void;
  /** Start a fresh conversation (new thread, cleared transcript). */
  onNewChat?: () => void;
  /** Whether the new-chat action is currently unavailable (boot/reconnect). */
  newChatDisabled?: boolean;
  /** Current accessibility preferences (text size). */
  prefs: A11yPrefs;
  /** Apply a preference change. */
  onChangePrefs: (patch: Partial<A11yPrefs>) => void;
}

/** Compose-new glyph (a note with a pencil) — start a fresh chat. */
function NewChatIcon() {
  return (
    <svg viewBox="0 0 24 24" width="19" height="19" fill="none" aria-hidden="true" focusable="false">
      <path
        d="M12 5H7a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M17.4 3.9a1.6 1.6 0 0 1 2.3 2.3l-7.1 7.1-3 .7.7-3 7.1-7.1Z"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true" focusable="false">
      <path
        d="M6 6l12 12M18 6L6 18"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** Small "sparkle" glyph for the assistant avatar (decorative). */
function SparkIcon() {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="currentColor" aria-hidden="true" focusable="false">
      <path d="M12 2.5l1.8 4.9 4.9 1.8-4.9 1.8L12 15.9l-1.8-4.9L5.3 9.2l4.9-1.8L12 2.5Z" />
      <path d="M18.5 14.5l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9.9-2.4Z" opacity="0.85" />
    </svg>
  );
}

/** Panel header: an assistant avatar, product name, an "AI" badge, a new-chat
    action, accessibility settings, and a close button. */
export function WidgetHeader({
  onClose,
  onNewChat,
  newChatDisabled,
  prefs,
  onChangePrefs,
}: WidgetHeaderProps) {
  return (
    <header className="cadre-header">
      <div className="cadre-header__title">
        <span className="cadre-header__avatar" aria-hidden="true">
          <SparkIcon />
        </span>
        <span className="cadre-header__name">Cadre AI Assistant</span>
        <span className="cadre-header__badge" title="Powered by AI">
          AI
        </span>
      </div>
      <div className="cadre-header__actions">
        <button
          type="button"
          className="cadre-header__icon-btn"
          aria-label="New chat"
          title="New chat"
          onClick={onNewChat}
          disabled={newChatDisabled || !onNewChat}
        >
          <NewChatIcon />
        </button>
        <SettingsMenu prefs={prefs} onChange={onChangePrefs} />
        <button
          type="button"
          className="cadre-header__icon-btn"
          aria-label="Close chat"
          onClick={onClose}
        >
          <CloseIcon />
        </button>
      </div>
    </header>
  );
}
