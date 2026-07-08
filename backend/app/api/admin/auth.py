"""Admin authentication + roles (contracts §4).

Two roles: ``admin`` (full) and ``viewer`` (read-only). Masking is the default for
both; only ``admin`` may reveal PII, redeliver, or approve content. Auth is HTTP
Basic against config credentials — a dev stub for the V1 role model that a real
identity provider (OIDC/SAML) replaces by swapping ``require_admin``'s body. HTTPS
is assumed in front of this.
"""

import secrets
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.core.config import get_settings

_basic = HTTPBasic()

AdminRole = Literal["admin", "viewer"]


@dataclass(frozen=True)
class AdminPrincipal:
    username: str
    role: AdminRole


def _matches(credentials: HTTPBasicCredentials, username: str, password: str) -> bool:
    # Compute both halves before the AND so the check is constant-time.
    user_ok = secrets.compare_digest(credentials.username.encode(), username.encode())
    pw_ok = secrets.compare_digest(credentials.password.encode(), password.encode())
    return user_ok and pw_ok


def require_admin(
    credentials: Annotated[HTTPBasicCredentials, Depends(_basic)],
) -> AdminPrincipal:
    """Authenticate any admin/viewer. Read routes accept either role."""
    settings = get_settings()
    if _matches(credentials, settings.admin_username, settings.admin_password.get_secret_value()):
        return AdminPrincipal(credentials.username, "admin")
    viewer_pw = settings.viewer_password.get_secret_value()
    if viewer_pw and _matches(credentials, settings.viewer_username, viewer_pw):
        return AdminPrincipal(credentials.username, "viewer")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid admin credentials.",
        headers={"WWW-Authenticate": "Basic"},
    )


def require_admin_role(
    credentials: Annotated[HTTPBasicCredentials, Depends(_basic)],
) -> AdminPrincipal:
    """Authenticate AND require the ``admin`` role. Write / reveal / approve routes
    use this — a viewer is authenticated but 403'd (not 401)."""
    principal = require_admin(credentials)
    if principal.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires the admin role.",
        )
    return principal


# Read access (admin or viewer); write/reveal access (admin only).
AdminDep = Annotated[AdminPrincipal, Depends(require_admin)]
AdminRoleDep = Annotated[AdminPrincipal, Depends(require_admin_role)]
