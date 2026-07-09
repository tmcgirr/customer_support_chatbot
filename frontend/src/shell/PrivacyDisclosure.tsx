import { PRIVACY_URL, PRIVACY_VERSION } from "../config";

/**
 * Privacy / AI-use disclosure shown once inside the opening (welcome) message —
 * see WelcomeChips. The copy is fixed and must render verbatim. "Privacy Notice"
 * links to the production privacy URL (configurable per environment via VITE_PRIVACY_URL).
 */
export function PrivacyDisclosure() {
  return (
    <p className="cadre-privacy" data-privacy-version={PRIVACY_VERSION}>
      This chat uses AI and may store your messages to answer questions, provide support, and
      improve Cadre&apos;s services. Do not enter passwords, authentication codes, or highly
      sensitive information. See our{" "}
      <a href={PRIVACY_URL} target="_blank" rel="noopener noreferrer">
        Privacy Notice
      </a>{" "}
      for details.
    </p>
  );
}
