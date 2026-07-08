import { PRIVACY_VERSION } from "../config";

/**
 * Persistent privacy / AI-use disclosure shown near the bottom of the panel.
 * The copy is fixed and must render verbatim.
 */
export function PrivacyDisclosure() {
  return (
    <p className="cadre-privacy" data-privacy-version={PRIVACY_VERSION}>
      This chat uses AI and may store your messages to answer questions, provide support, and
      improve Cadre&apos;s services. Do not enter passwords, authentication codes, or highly
      sensitive information. See our Privacy Notice for details.
    </p>
  );
}
