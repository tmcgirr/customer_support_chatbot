// Host <-> widget communication.
//
// The widget always runs inside an iframe. It talks to the embedding host page
// ONLY through `window.postMessage`, and every message is stamped with a source
// discriminator plus an explicit target/allowed origin. We never post to "*"
// unless the widget is explicitly configured for a single wildcard origin (dev),
// and on receive we drop any event whose origin or source we don't trust.

import { ALLOWED_HOST_ORIGINS } from "../config";

/** Discriminator stamped on every message the widget sends to the host. */
export const WIDGET_SOURCE = "cadre-widget";
/** Discriminator we require on every message accepted from the host. */
export const HOST_SOURCE = "cadre-host";

/** Envelope shape posted to the host. */
interface WidgetMessage {
  source: typeof WIDGET_SOURCE;
  type: string;
  payload?: unknown;
}

/** Shape we tentatively read off an inbound event before validating it. */
interface InboundMessage {
  source?: unknown;
  type?: unknown;
  payload?: unknown;
}

/** True when the widget is configured with exactly one wildcard origin. */
function isSingleWildcard(): boolean {
  return ALLOWED_HOST_ORIGINS.length === 1 && ALLOWED_HOST_ORIGINS[0] === "*";
}

/** True when an inbound event origin is trusted. */
function isTrustedOrigin(origin: string): boolean {
  // On receive we allow any origin only if "*" is present in the allow-list.
  if (ALLOWED_HOST_ORIGINS.includes("*")) return true;
  return ALLOWED_HOST_ORIGINS.includes(origin);
}

/**
 * Post a message up to the host page. Sends one message per configured origin so
 * each host only receives events targeted at its exact origin; falls back to the
 * "*" wildcard only when the single configured origin is itself "*".
 */
export function postToHost(type: string, payload?: unknown): void {
  const parent = window.parent;
  if (!parent) return;

  const message: WidgetMessage = { source: WIDGET_SOURCE, type, payload };

  if (isSingleWildcard()) {
    parent.postMessage(message, "*");
    return;
  }

  for (const origin of ALLOWED_HOST_ORIGINS) {
    // A concrete allow-list may still contain "*" alongside real origins; never
    // broadcast in that case — only target the explicit origins.
    if (origin === "*") continue;
    parent.postMessage(message, origin);
  }
}

/**
 * Subscribe to messages from the host. The handler is invoked only for events
 * that (a) come from a trusted origin and (b) carry `source: "cadre-host"` and a
 * string `type`. Returns an unsubscribe function.
 */
export function listenToHost(handler: (type: string, payload: unknown) => void): () => void {
  const onMessage = (event: MessageEvent): void => {
    if (!isTrustedOrigin(event.origin)) return;

    const data = event.data as InboundMessage | null;
    if (!data || typeof data !== "object") return;
    if (data.source !== HOST_SOURCE) return;
    if (typeof data.type !== "string") return;

    handler(data.type, data.payload);
  };

  window.addEventListener("message", onMessage);
  return () => window.removeEventListener("message", onMessage);
}
