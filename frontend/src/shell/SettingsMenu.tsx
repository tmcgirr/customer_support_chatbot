// Accessibility settings: a gear button in the header that opens a small popover
// to change the text size. Closes on outside click and Esc (Esc is stopped from
// bubbling so it doesn't also close the whole panel).

import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import type { A11yPrefs, FontScale } from "./useAccessibilityPrefs";

interface SettingsMenuProps {
  prefs: A11yPrefs;
  onChange: (patch: Partial<A11yPrefs>) => void;
}

// `sample` sizes the visible "A" so the control previews its own effect.
const SIZE_OPTIONS: ReadonlyArray<{ value: FontScale; label: string; sample: number }> = [
  { value: "default", label: "Default text size", sample: 13 },
  { value: "large", label: "Large text size", sample: 15 },
  { value: "larger", label: "Larger text size", sample: 18 },
];

/** Universal accessibility glyph (a figure in a circle) — this menu holds the
    text-size / accessibility controls, not general or theme settings. */
function AccessibilityIcon() {
  return (
    <svg viewBox="0 0 24 24" width="19" height="19" fill="none" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.7" />
      <circle cx="12" cy="7.3" r="1.3" fill="currentColor" />
      <path
        d="M7 9.6c1.55.72 3.28 1.08 5 1.08s3.45-.36 5-1.08"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
      <path d="M12 10.5v4.4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      <path
        d="M12 14.9l-2 4.05M12 14.9l2 4.05"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function SettingsMenu({ prefs, onChange }: SettingsMenuProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  // Close when a pointer press lands outside the menu.
  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape" && open) {
      // Swallow Esc so the panel's own Esc-to-close doesn't also fire.
      event.stopPropagation();
      setOpen(false);
      triggerRef.current?.focus();
    }
  };

  return (
    <div className="cadre-settings" ref={containerRef} onKeyDown={handleKeyDown}>
      <button
        ref={triggerRef}
        type="button"
        className="cadre-header__icon-btn"
        aria-label="Accessibility settings"
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        <AccessibilityIcon />
      </button>

      {open && (
        <div
          className="cadre-settings-popover"
          id={menuId}
          role="group"
          aria-label="Accessibility settings"
        >
          <div className="cadre-settings-group">
            <p className="cadre-settings-label">Text size</p>
            <div className="cadre-settings-options">
              {SIZE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className="cadre-settings-option cadre-settings-option--size"
                  aria-pressed={prefs.fontScale === option.value}
                  onClick={() => onChange({ fontScale: option.value })}
                >
                  <span aria-hidden="true" style={{ fontSize: option.sample }}>
                    A
                  </span>
                  <span className="cadre-sr-only">{option.label}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
