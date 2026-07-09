// Backend base URL (the widget talks only to Cadre APIs, never OpenAI/Mongo).
export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

// Consent/version strings surfaced on forms (contracts §3.4).
export const CONSENT_VERSION = "consent-2026-07";
export const PRIVACY_VERSION = "privacy-2026-07";

// Production website links (V7). Privacy points at the real published notice on
// cadreai.com; the client-portal URL is still owned by Client Success (no public
// login page yet, plan V7 §4) and stays a domain-consistent placeholder until
// confirmed. Both are overridden per environment via VITE_PRIVACY_URL /
// VITE_PORTAL_URL at build time.
export const PRIVACY_URL =
  import.meta.env.VITE_PRIVACY_URL ?? "https://www.cadreai.com/legal/privacy-policy";
export const PORTAL_URL = import.meta.env.VITE_PORTAL_URL ?? "https://portal.cadreai.com";

// Host-page origins allowed to embed and message the widget. "*" is a dev
// default; production must set VITE_ALLOWED_ORIGINS to real origins.
export const ALLOWED_HOST_ORIGINS: string[] = (import.meta.env.VITE_ALLOWED_ORIGINS ?? "*")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

// Fail CLOSED in production: a prod build MUST pin real https host origins. A wildcard
// (or unset) default would let ANY page embed + postMessage the widget, mirroring the
// backend's fail-closed CORS guard (SECURITY_REVIEW_V1 M4). Dev/test builds keep "*".
if (
  import.meta.env.PROD &&
  (ALLOWED_HOST_ORIGINS.length === 0 || ALLOWED_HOST_ORIGINS.includes("*"))
) {
  throw new Error(
    "VITE_ALLOWED_ORIGINS must be set to explicit https origins for a production build (no '*').",
  );
}
