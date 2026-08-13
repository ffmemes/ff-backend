"""Admin API token auth.

Agents and operators call admin routes with either:
  Authorization: Bearer <ADMIN_API_TOKEN>
or
  X-Admin-Token: <ADMIN_API_TOKEN>
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from src.config import settings


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def require_admin_token(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    configured = settings.ADMIN_API_TOKEN
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_API_TOKEN is not configured",
        )

    presented = x_admin_token.strip() if x_admin_token else None
    if not presented:
        presented = _extract_bearer(authorization)

    if not presented or not secrets.compare_digest(presented, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )
