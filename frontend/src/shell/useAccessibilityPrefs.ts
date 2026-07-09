// User accessibility preferences for the widget: a text-size scale. Not sensitive,
// so it persists in localStorage (guarded — a sandboxed iframe may deny storage)
// and applies for the session regardless.

import { useCallback, useEffect, useState } from "react";

export type FontScale = "default" | "large" | "larger";

export interface A11yPrefs {
  fontScale: FontScale;
}

/** Multiplier applied to the widget's text sizes via the --cadre-font-scale var. */
export const FONT_SCALE_VALUE: Record<FontScale, number> = {
  default: 1,
  large: 1.15,
  larger: 1.3,
};

const STORAGE_KEY = "cadre.a11y.v1";
const DEFAULT_PREFS: A11yPrefs = { fontScale: "default" };

function loadPrefs(): A11yPrefs {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw) as Partial<A11yPrefs>;
    return {
      fontScale:
        parsed.fontScale === "large" || parsed.fontScale === "larger"
          ? parsed.fontScale
          : "default",
    };
  } catch {
    return DEFAULT_PREFS;
  }
}

export function useAccessibilityPrefs() {
  const [prefs, setPrefs] = useState<A11yPrefs>(loadPrefs);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch {
      // Storage may be unavailable (sandboxed iframe / private mode); the choice
      // still applies for this session.
    }
  }, [prefs]);

  const update = useCallback((patch: Partial<A11yPrefs>) => {
    setPrefs((prev) => ({ ...prev, ...patch }));
  }, []);

  return { prefs, update };
}
