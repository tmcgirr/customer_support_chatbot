// Backend base URL (the widget talks only to Cadre APIs, never OpenAI/Mongo).
export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

// Consent/version strings surfaced on forms (contracts §3.4).
export const CONSENT_VERSION = "consent-2026-07";
export const PRIVACY_VERSION = "privacy-2026-07";

// Production website links (V7). The REAL URLs are owned by Legal / Client Success
// (blocked-on, plan V7 §4); these placeholders are overridden per environment via
// VITE_PRIVACY_URL / VITE_PORTAL_URL at build time.
export const PRIVACY_URL = import.meta.env.VITE_PRIVACY_URL ?? "https://cadre.ai/privacy";
export const PORTAL_URL = import.meta.env.VITE_PORTAL_URL ?? "https://portal.cadre.ai";

// Host-page origins allowed to embed and message the widget. "*" is a dev
// default; production must set VITE_ALLOWED_ORIGINS to real origins.
export const ALLOWED_HOST_ORIGINS: string[] = (import.meta.env.VITE_ALLOWED_ORIGINS ?? "*")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);
