// Validated categorical palette for the admin dashboard charts.
//
// The admin ships a single warm-cream theme (mirroring the chat widget), so charts
// are validated for LIGHT mode only, against the cream chart surface (#f7f3ea).
// Every hue was checked with the dataviz validator — lightness band, chroma floor,
// adjacent-pair CVD separation, and ≥3:1 contrast vs. the surface all PASS.
//
//   node scripts/validate_palette.js "#e2543b,#3f6fb0,#b0700c,#0f9c8a,#8a4fbf" \
//        --mode light --surface "#f7f3ea"
//
// The ORDER is load-bearing: it keeps the CVD-confusable pair (blue ↔ violet)
// non-adjacent. Do not reorder or swap a hue without re-running the validator.

/** The cream chart surface every hue is validated against. */
export const CHART_SURFACE = "#f7f3ea";

/** Fixed categorical order. Assign by entity, never cycle, never by rank. */
export const CATEGORICAL = [
  "#e2543b", // coral (Cadre brand accent)
  "#3f6fb0", // blue
  "#b0700c", // amber
  "#0f9c8a", // teal
  "#8a4fbf", // violet
] as const;

/** Brand coral — the single hue for magnitude bars (length encodes the value). */
export const BRAND = "#e2543b";

/** Trend series colors (2): conversations = coral, requests = blue (ΔE > 70). */
export const SERIES = {
  conversations: "#e2543b",
  requests: "#3f6fb0",
} as const;

/** Reserved status hues — never reused as a categorical "series N". */
export const STATUS = {
  good: "#2f7d4f",
  warning: "#b0700c",
  critical: "#c0392b",
} as const;

/** Muted ink for an overflow entity (a 6th+ slice folds here, never a new hue). */
export const OVERFLOW = "#8a8272";

/** Stable color for the i-th entity in fixed categorical order; overflow → muted. */
export function categorical(i: number): string {
  return CATEGORICAL[i] ?? OVERFLOW;
}
