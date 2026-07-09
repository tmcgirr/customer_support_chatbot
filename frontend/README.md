# Frontend — Cadre AI chatbot

React + TypeScript (Vite). Two apps from one codebase: the **public chat widget** (embedded in an
iframe on the marketing site) and the **admin console** (an internal SPA).

See the repo [README](../README.md) and the [Capabilities Catalog](../docs/capabilities/) for the
product picture; this file is the developer orientation.

## Entry points & layout

- `index.html` → the **chat widget** (runs inside an `iframe`; talks to the host page only via
  origin-checked `postMessage`).
- `admin.html` → the **admin console** (separate entry; credentials/tokens held in memory only,
  never `localStorage`).

```
src/
  conversation/   the chat transcript + streaming message UI
  forms/          the request forms (strategy call / portal support / escalation)
  shell/          widget chrome — frame, header, reconnect/degraded states, a11y
  host/           iframe ↔ host-page postMessage bridge
  admin/          the admin SPA — dashboard, conversations, requests, knowledge,
                  insights, funnel, canonical, audit, privacy, monitoring
  api/            shared client helpers
```

## Commands

```bash
pnpm install
pnpm dev            # widget on :5273 + admin (admin.html)
pnpm build          # type-check + production build
pnpm test           # unit/component tests (Vitest + Testing Library)
```

## Conventions

- The widget runs in an iframe for isolation from host-page CSS/JS; host communication is only via
  origin-checked `postMessage`.
- The API base is configured at build time (`VITE_API_BASE`); see `src/config`.
- Nothing sensitive in `localStorage`; admin credentials live in React memory only.
- Answers stream over Server-Sent Events; the transcript is rendered incrementally.
