import { BRAND } from "./palette";

export interface BarDatum {
  label: string;
  value: number;
}

/**
 * Horizontal magnitude bars (e.g. top topics). Magnitude is encoded by LENGTH, so
 * every bar is the same single hue (brand coral) — color carries no meaning here.
 * Bars are sorted high→low by the caller and each carries a direct value label, so
 * no axis or hover is strictly required; a row highlight aids scanning.
 */
export default function BarList({
  title,
  data,
  color = BRAND,
  emptyText = "No data yet.",
  maxRows = 8,
}: {
  title: string;
  data: BarDatum[];
  color?: string;
  emptyText?: string;
  maxRows?: number;
}) {
  const rows = data.slice(0, maxRows);
  const max = rows.reduce((m, d) => Math.max(m, d.value), 0);

  return (
    <div className="admin-card admin-chart">
      <h3 className="admin-chart-title">{title}</h3>
      {rows.length === 0 || max === 0 ? (
        <p className="admin-muted">{emptyText}</p>
      ) : (
        <ul className="admin-barlist">
          {rows.map((d) => {
            const width = max > 0 ? Math.max((d.value / max) * 100, 1.5) : 0;
            return (
              <li key={d.label} className="admin-bar-row" title={`${d.label}: ${d.value}`}>
                <span className="admin-bar-label">{d.label}</span>
                <span className="admin-bar-track">
                  <span
                    className="admin-bar-fill"
                    style={{ width: `${width}%`, background: color }}
                  />
                </span>
                <span className="admin-bar-value">{d.value}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
