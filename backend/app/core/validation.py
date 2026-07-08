"""Small shared input validators (kept provider- and framework-agnostic)."""

import re

# Deliberately permissive: one @, a dot in the domain, no spaces. We are not an
# email-verification service — this only rejects obviously-malformed input before
# it is stored or used to match a subject. Real reachability is proven out of band.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(value: str | None) -> bool:
    return _EMAIL_RE.match((value or "").strip()) is not None
