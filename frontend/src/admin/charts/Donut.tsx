import { useRef, useState } from "react";

import { ChartTip, relCoords, useTip } from "./Tooltip";

export interface DonutSlice {
  label: string;
  value: number;
  color: string;
}

const SIZE = 176;
const STROKE = 26;
const R = SIZE / 2 - STROKE / 2 - 2;
const C = 2 * Math.PI * R;
const CENTER = SIZE / 2;

function pct(value: number, total: number): number {
  return total > 0 ? Math.round((value / total) * 100) : 0;
}

/**
 * Donut chart for a categorical breakdown (identity/state — e.g. conversations by
 * outcome). Slices arrive pre-colored (the caller assigns hue by entity, in fixed
 * order). The legend lists every value, so identity is never color-alone and it
 * doubles as the required table view. A 2px surface gap separates segments.
 */
export default function Donut({
  title,
  slices,
  centerLabel = "Total",
  emptyText = "No data yet.",
}: {
  title: string;
  slices: DonutSlice[];
  centerLabel?: string;
  emptyText?: string;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const { tip, show, hide } = useTip();
  const [active, setActive] = useState<number | null>(null);

  const drawn = slices.filter((s) => s.value > 0);
  const total = drawn.reduce((sum, s) => sum + s.value, 0);

  const summary = drawn.map((s) => `${s.label} ${s.value} (${pct(s.value, total)}%)`).join(", ");

  const centerValue = active != null && drawn[active] ? drawn[active].value : total;
  const centerText = active != null && drawn[active] ? drawn[active].label : centerLabel;

  let cumulative = 0;
  const gapLen = drawn.length > 1 ? 3 : 0;

  return (
    <div className="admin-card admin-chart">
      <h3 className="admin-chart-title">{title}</h3>
      {total === 0 ? (
        <p className="admin-muted">{emptyText}</p>
      ) : (
        <div className="admin-donut">
          <div className="admin-chart-plot admin-donut-ring" ref={wrapRef}>
            <svg
              width={SIZE}
              height={SIZE}
              viewBox={`0 0 ${SIZE} ${SIZE}`}
              role="img"
              aria-label={`${title}. ${summary}`}
            >
              <circle
                cx={CENTER}
                cy={CENTER}
                r={R}
                fill="none"
                stroke="var(--admin-track)"
                strokeWidth={STROKE}
              />
              <g transform={`rotate(-90 ${CENTER} ${CENTER})`}>
                {drawn.map((s, i) => {
                  const dash = (s.value / total) * C;
                  const visible = Math.max(dash - gapLen, 0.001);
                  const node = (
                    <circle
                      key={s.label}
                      cx={CENTER}
                      cy={CENTER}
                      r={R}
                      fill="none"
                      stroke={s.color}
                      strokeWidth={active === i ? STROKE + 4 : STROKE}
                      strokeDasharray={`${visible} ${C - visible}`}
                      strokeDashoffset={-cumulative}
                      style={{ cursor: "default", transition: "stroke-width 0.12s ease" }}
                      onMouseEnter={(e) => {
                        setActive(i);
                        const { x, y } = relCoords(wrapRef, e);
                        show(x, y, `${s.label}: ${s.value} (${pct(s.value, total)}%)`);
                      }}
                      onMouseMove={(e) => {
                        const { x, y } = relCoords(wrapRef, e);
                        show(x, y, `${s.label}: ${s.value} (${pct(s.value, total)}%)`);
                      }}
                      onMouseLeave={() => {
                        setActive(null);
                        hide();
                      }}
                    />
                  );
                  cumulative += dash;
                  return node;
                })}
              </g>
              <text
                x={CENTER}
                y={CENTER - 4}
                textAnchor="middle"
                className="admin-donut-value"
              >
                {centerValue}
              </text>
              <text
                x={CENTER}
                y={CENTER + 16}
                textAnchor="middle"
                className="admin-donut-label"
              >
                {centerText}
              </text>
            </svg>
            <ChartTip tip={tip} />
          </div>

          <ul className="admin-legend">
            {drawn.map((s, i) => (
              <li
                key={s.label}
                className={active === i ? "admin-legend-row is-active" : "admin-legend-row"}
                onMouseEnter={() => setActive(i)}
                onMouseLeave={() => setActive(null)}
              >
                <span className="admin-legend-swatch" style={{ background: s.color }} aria-hidden />
                <span className="admin-legend-name">{s.label}</span>
                <span className="admin-legend-value">{s.value}</span>
                <span className="admin-legend-pct">{pct(s.value, total)}%</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
