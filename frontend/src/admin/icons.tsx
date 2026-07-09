// Minimal inline line-icons (24-grid, 1.7 stroke). Decorative — every icon is
// aria-hidden and sits next to a text label that carries the accessible name.

import type { ReactNode } from "react";

type IconProps = { size?: number };

function svg(size: number, children: ReactNode) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

export const Icons: Record<string, (p: IconProps) => JSX.Element> = {
  dashboard: ({ size = 18 }) =>
    svg(
      size,
      <>
        <rect x="3" y="3" width="7" height="9" rx="1.5" />
        <rect x="14" y="3" width="7" height="5" rx="1.5" />
        <rect x="14" y="12" width="7" height="9" rx="1.5" />
        <rect x="3" y="16" width="7" height="5" rx="1.5" />
      </>,
    ),
  insights: ({ size = 18 }) =>
    svg(
      size,
      <>
        <path d="M4 19V5" />
        <path d="M4 15l4-4 3 3 6-7" />
        <path d="M17 7h3v3" />
      </>,
    ),
  funnel: ({ size = 18 }) =>
    svg(
      size,
      <>
        <path d="M3 4h18l-7 8v6l-4 2v-8L3 4Z" />
      </>,
    ),
  conversations: ({ size = 18 }) =>
    svg(
      size,
      <>
        <path d="M4 5h16v10H8l-4 4V5Z" />
        <path d="M8 9h8M8 12h5" />
      </>,
    ),
  requests: ({ size = 18 }) =>
    svg(
      size,
      <>
        <path d="M3 7l9 6 9-6" />
        <rect x="3" y="5" width="18" height="14" rx="2" />
      </>,
    ),
  knowledge: ({ size = 18 }) =>
    svg(
      size,
      <>
        <path d="M5 4h11a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2V4Z" />
        <path d="M9 4v13" />
        <path d="M18 16H7a2 2 0 0 0-2 2" />
      </>,
    ),
  canonical: ({ size = 18 }) =>
    svg(
      size,
      <>
        <path d="M6 3h9l4 4v14H6V3Z" />
        <path d="M14 3v5h5" />
        <path d="M9.5 14.5l2 2 4-4.5" />
      </>,
    ),
  unresolved: ({ size = 18 }) =>
    svg(
      size,
      <>
        <path d="M12 3l9 16H3l9-16Z" />
        <path d="M12 10v4" />
        <path d="M12 17h.01" />
      </>,
    ),
  audit: ({ size = 18 }) =>
    svg(
      size,
      <>
        <path d="M9 3h6l1 3H8l1-3Z" />
        <rect x="4" y="6" width="16" height="15" rx="2" />
        <path d="M8 11h8M8 15h6" />
      </>,
    ),
  privacy: ({ size = 18 }) =>
    svg(
      size,
      <>
        <path d="M12 3l7 3v5c0 5-3.5 8-7 10-3.5-2-7-5-7-10V6l7-3Z" />
        <path d="M9.5 12l1.8 1.8 3.2-3.6" />
      </>,
    ),
  search: ({ size = 18 }) =>
    svg(
      size,
      <>
        <circle cx="11" cy="11" r="7" />
        <path d="M20 20l-3.5-3.5" />
      </>,
    ),
  refresh: ({ size = 16 }) =>
    svg(
      size,
      <>
        <path d="M21 12a9 9 0 1 1-2.64-6.36" />
        <path d="M21 4v5h-5" />
      </>,
    ),
  logout: ({ size = 16 }) =>
    svg(
      size,
      <>
        <path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3" />
        <path d="M10 12H3m0 0 3-3m-3 3 3 3" />
      </>,
    ),
  spark: ({ size = 18 }) =>
    svg(
      size,
      <>
        <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z" fill="currentColor" stroke="none" />
      </>,
    ),
  target: ({ size = 18 }) =>
    svg(
      size,
      <>
        <circle cx="12" cy="12" r="8" />
        <circle cx="12" cy="12" r="4" />
        <circle cx="12" cy="12" r="0.6" fill="currentColor" />
      </>,
    ),
  model: ({ size = 18 }) =>
    svg(
      size,
      <>
        <rect x="7" y="7" width="10" height="10" rx="2" />
        <path d="M10 3v2M14 3v2M10 19v2M14 19v2M3 10h2M3 14h2M19 10h2M19 14h2" />
      </>,
    ),
  cost: ({ size = 18 }) =>
    svg(
      size,
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v10M14.5 9.2A2.6 2.6 0 0 0 12 8c-1.4 0-2.5.8-2.5 2s1.1 1.8 2.5 1.8 2.5.8 2.5 2-1.1 2-2.5 2a2.6 2.6 0 0 1-2.5-1.2" />
      </>,
    ),
};

export function Icon({ name, size }: { name: string; size?: number }) {
  const Cmp = Icons[name] ?? Icons.dashboard;
  return <Cmp size={size} />;
}
