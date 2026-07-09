import { type ReactNode, type RefObject, useState } from "react";

/**
 * Shared floating tooltip for the dashboard charts. The chart wraps its plot in a
 * `position: relative` container (see `.admin-chart-plot` in admin.css) and the tip
 * is positioned in that container's coordinate space. Reduced-motion is honoured by
 * the global CSS rule; the tip itself has no animation.
 */
export interface TipState {
  x: number;
  y: number;
  content: ReactNode | null;
}

export function useTip() {
  const [tip, setTip] = useState<TipState>({ x: 0, y: 0, content: null });
  return {
    tip,
    show(x: number, y: number, content: ReactNode) {
      setTip({ x, y, content });
    },
    hide() {
      setTip((prev) => (prev.content == null ? prev : { ...prev, content: null }));
    },
  };
}

/** Mouse coordinates relative to a wrapper element (for tip placement). */
export function relCoords(
  ref: RefObject<HTMLElement | null>,
  event: { clientX: number; clientY: number },
): { x: number; y: number } {
  const rect = ref.current?.getBoundingClientRect();
  if (!rect) return { x: 0, y: 0 };
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

export function ChartTip({ tip }: { tip: TipState }) {
  if (tip.content == null) return null;
  return (
    <div className="admin-chart-tip" role="tooltip" style={{ left: tip.x, top: tip.y }}>
      {tip.content}
    </div>
  );
}
