import { useMemo, useState } from "react";

// Small, shared list controls: a click-to-sort table header + a filter <select>,
// operating on the already-fetched rows (client-side). Keeps every admin list
// consistent without per-view boilerplate.

export type SortDir = "asc" | "desc";
export interface SortState {
  key: string;
  dir: SortDir;
}

type Accessor<T> = (row: T) => string | number | null | undefined;

/**
 * Sort `rows` by the active column. `accessors` maps a column key to a value
 * extractor and MUST be a stable reference (define it at module scope), so it can
 * sit in the memo deps without re-sorting every render. Nulls sort last.
 */
export function useSort<T>(
  rows: T[],
  accessors: Record<string, Accessor<T>>,
  initial: SortState,
) {
  const [sort, setSort] = useState<SortState>(initial);

  const sorted = useMemo(() => {
    const acc = accessors[sort.key];
    if (!acc) return rows;
    return [...rows].sort((a, b) => {
      const av = acc(a);
      const bv = acc(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp =
        typeof av === "number" && typeof bv === "number"
          ? av - bv
          : String(av).localeCompare(String(bv));
      return sort.dir === "asc" ? cmp : -cmp;
    });
  }, [rows, sort, accessors]);

  function toggle(key: string) {
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));
  }

  return { sorted, sort, toggle };
}

/** A clickable, sortable table header cell with a direction caret. */
export function SortHeader({
  label,
  sortKey,
  sort,
  onToggle,
  numeric,
}: {
  label: string;
  sortKey: string;
  sort: SortState;
  onToggle: (key: string) => void;
  numeric?: boolean;
}) {
  const active = sort.key === sortKey;
  return (
    <th
      className={`admin-th-sort${numeric ? " admin-num" : ""}${active ? " is-active" : ""}`}
      aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
      onClick={() => onToggle(sortKey)}
    >
      <span className="admin-th-inner">
        {label}
        <span className="admin-th-caret" aria-hidden="true">
          {active ? (sort.dir === "asc" ? "▲" : "▼") : "↕"}
        </span>
      </span>
    </th>
  );
}

/** Distinct, sorted, non-empty values of a field across rows — for filter options. */
export function distinct<T>(rows: T[], accessor: (row: T) => string | null | undefined): string[] {
  const set = new Set<string>();
  for (const r of rows) {
    const v = accessor(r);
    if (v) set.add(v);
  }
  return [...set].sort();
}

/** A labelled filter dropdown with an "All" default (empty value = no filter). */
export function FilterSelect({
  label,
  value,
  options,
  onChange,
  allLabel = "All",
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  allLabel?: string;
}) {
  return (
    <label>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{allLabel}</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}
