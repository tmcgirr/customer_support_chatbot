"""Admin authentication — HTTP Basic (POC single login; V1 adds an IdP + roles).

A separate auth surface from the public session token (contracts §4). HTTPS is
assumed in front of this in any real deployment.
"""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.core.config import get_settings

_basic = HTTPBasic()


def require_admin(credentials: Annotated[HTTPBasicCredentials, Depends(_basic)]) -> str:
    settings = get_settings()
    user_ok = secrets.compare_digest(
        credentials.username.encode(), settings.admin_username.encode()
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode(), settings.admin_password.get_secret_value().encode()
    )
    if not (user_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


AdminDep = Annotated[str, Depends(require_admin)]
