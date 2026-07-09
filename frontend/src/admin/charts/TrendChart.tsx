import { type MouseEvent, useRef, useState } from "react";

import { ChartTip, relCoords, useTip } from "./Tooltip";

export interface TrendSeries {
  key: string;
  label: string;
  color: string;
  values: number[];
}

// Fixed drawing space; the SVG scales to the container width (aspect ratio fixed).
// Strokes use non-scaling-stroke so they stay a crisp 2px at any render size.
const VB_W = 720;
const VB_H = 260;
const PAD_L = 44;
const PAD_R = 16;
const PAD_T = 16;
const PAD_B = 28;
const PLOT_W = VB_W - PAD_L - PAD_R;
const PLOT_H = VB_H - PAD_T - PAD_B;

/** Round a max up to a friendly axis ceiling (1, 2, 5 × 10ⁿ). */
function niceCeil(value: number): number {
  if (value <= 0) return 1;
  const pow = Math.pow(10, Math.floor(Math.log10(value)));
  const n = value / pow;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * pow;
}

/** "2026-07-09" → "7/9" without constructing a Date. */
function shortDate(iso: string): string {
  const parts = iso.split("-");
  if (parts.length !== 3) return iso;
  return `${Number(parts[1])}/${Number(parts[2])}`;
}

/**
 * Multi-series trend (area + 2px line) on a SINGLE count axis — conversations and
 * requests are both counts, so they share one scale (never a dual axis). A legend
 * names the series (identity is never color-alone) and a crosshair + tooltip reads
 * out every series' value at the hovered day.
 */
export default function TrendChart({
  title,
  labels,
  series,
  emptyText = "The trend appears once the daily snapshot job has recorded a few days.",
}: {
  title: string;
  labels: string[];
  series: TrendSeries[];
  emptyText?: string;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const { tip, show, hide } = useTip();
  const [active, setActive] = useState<number | null>(null);

  const n = labels.length;
  const rawMax = series.reduce((m, s) => Math.max(m, ...s.values, 0), 0);

  if (n < 2 || rawMax === 0) {
    return (
      <div className="admin-card admin-chart admin-chart-wide">
        <h3 className="admin-chart-title">{title}</h3>
        <div className="admin-chart-empty">{emptyText}</div>
      </div>
    );
  }

  const max = niceCeil(rawMax);
  const x = (i: number) => PAD_L + (i / (n - 1)) * PLOT_W;
  const y = (v: number) => PAD_T + (1 - v / max) * PLOT_H;

  const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    value: Math.round(max * f),
    yPos: PAD_T + (1 - f) * PLOT_H,
  }));

  const tickEvery = Math.max(1, Math.ceil(n / 6));

  function line(values: number[]): string {
    return values.map((v, i) => `${i === 0 ? "M" : "L"} ${x(i)} ${y(v)}`).join(" ");
  }
  function area(values: number[]): string {
    const base = PAD_T + PLOT_H;
    return `${line(values)} L ${x(n - 1)} ${base} L ${x(0)} ${base} Z`;
  }

  function onMove(event: MouseEvent) {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    const padLeftPx = (PAD_L / VB_W) * rect.width;
    const plotPx = (PLOT_W / VB_W) * rect.width;
    const frac = (event.clientX - rect.left - padLeftPx) / plotPx;
    const idx = Math.min(n - 1, Math.max(0, Math.round(frac * (n - 1))));
    setActive(idx);
    const { x: tx, y: ty } = relCoords(wrapRef, event);
    show(
      tx,
      ty,
      <>
        <div className="admin-tip-date">{labels[idx]}</div>
        {series.map((s) => (
          <div key={s.key} className="admin-tip-row">
            <span className="admin-tip-swatch" style={{ background: s.color }} />
            {s.label}: <strong>{s.values[idx]}</strong>
          </div>
        ))}
      </>,
    );
  }

  const summary = series.map((s) => `${s.label} ${s.values[n - 1]} latest`).join(", ");

  return (
    <div className="admin-card admin-chart admin-chart-wide">
      <div className="admin-chart-head">
        <h3 className="admin-chart-title">{title}</h3>
        <ul className="admin-legend admin-legend-inline">
          {series.map((s) => (
            <li key={s.key} className="admin-legend-row">
              <span className="admin-legend-swatch" style={{ background: s.color }} aria-hidden />
              <span className="admin-legend-name">{s.label}</span>
            </li>
          ))}
        </ul>
      </div>
      <div
        className="admin-chart-plot"
        ref={wrapRef}
        onMouseMove={onMove}
        onMouseLeave={() => {
          setActive(null);
          hide();
        }}
      >
        <svg
          className="admin-trend-svg"
          viewBox={`0 0 ${VB_W} ${VB_H}`}
          role="img"
          aria-label={`${title}. ${summary}.`}
        >
          {grid.map((g) => (
            <g key={g.value}>
              <line
                x1={PAD_L}
                y1={g.yPos}
                x2={VB_W - PAD_R}
                y2={g.yPos}
                stroke="var(--admin-grid)"
                strokeWidth={1}
                vectorEffect="non-scaling-stroke"
              />
              <text x={PAD_L - 8} y={g.yPos + 4} textAnchor="end" className="admin-axis-label">
                {g.value}
              </text>
            </g>
          ))}

          {labels.map((label, i) =>
            i % tickEvery === 0 || i === n - 1 ? (
              <text
                key={label + i}
                x={x(i)}
                y={VB_H - 8}
                textAnchor="middle"
                className="admin-axis-label"
              >
                {shortDate(label)}
              </text>
            ) : null,
          )}

          {series.map((s) => (
            <path key={`a-${s.key}`} d={area(s.values)} fill={s.color} opacity={0.12} />
          ))}
          {series.map((s) => (
            <path
              key={`l-${s.key}`}
              d={line(s.values)}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          ))}

          {active != null && (
            <g>
              <line
                x1={x(active)}
                y1={PAD_T}
                x2={x(active)}
                y2={PAD_T + PLOT_H}
                stroke="var(--admin-crosshair)"
                strokeWidth={1}
                vectorEffect="non-scaling-stroke"
              />
              {series.map((s) => (
                <circle
                  key={`d-${s.key}`}
                  cx={x(active)}
                  cy={y(s.values[active])}
                  r={4}
                  fill="var(--admin-surface)"
                  stroke={s.color}
                  strokeWidth={2}
                  vectorEffect="non-scaling-stroke"
                />
              ))}
            </g>
          )}
        </svg>
        <ChartTip tip={tip} />
      </div>
    </div>
  );
}
