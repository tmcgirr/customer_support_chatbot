"""PII masking for admin views (contracts §10). Emails and phone numbers in any
free text (transcripts, unresolved questions) are masked before an admin sees them.
Masking is applied at READ time so the verbatim value stays available for a future
audited reveal."""

import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# A run of digits with common phone separators (7-15 digits after stripping).
_PHONE_RE = re.compile(r"\+?\d[\d\s().\-]{5,}\d")


def mask_email(email: str | None) -> str:
    """``ada@acme.com`` -> ``a***@acme.com``. Never reveals more than the first
    local-part character; robust for odd/malformed input."""
    if not email:
        return ""
    local, sep, domain = email.partition("@")
    if not sep:
        return "***"
    masked_local = f"{local[0]}***" if local else "***"
    return f"{masked_local}@{domain}"


def mask_company(company: str | None) -> str | None:
    """A company name identifies a prospective client (content rule: never confirm who
    is a client). Redact it in list views; the full value is available only via the
    audited reveal endpoint, exactly like email (SECURITY_REVIEW_V1 L5). Returns None
    when absent so the UI shows nothing, and a fixed redaction marker when present."""
    if not company or not company.strip():
        return None
    return "•••"


def mask_emails_in_text(text: str) -> str:
    return _EMAIL_RE.sub(lambda match: mask_email(match.group(0)), text)


def _mask_phone(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if not (7 <= len(digits) <= 15):
        return match.group(0)  # not phone-length; leave it (e.g. a short code)
    return f"***-***-{digits[-2:]}"


def mask_phones_in_text(text: str) -> str:
    return _PHONE_RE.sub(_mask_phone, text)


def mask_pii_in_text(text: str) -> str:
    """Mask emails AND phone numbers in free text (contracts §10)."""
    return mask_phones_in_text(mask_emails_in_text(text))
