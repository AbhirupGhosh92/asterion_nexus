"""
Firebase Auth verification + RBAC.

Identity model:
  - Every request carries `Authorization: Bearer <Firebase ID token>`.
  - The token is verified server-side with firebase-admin (signature, expiry,
    audience). Cloud Run being network-open is fine — nothing executes
    without a valid token.
  - RBAC tiers live in Firebase custom claims: {"tier": "free"|"pro"|"admin"}.
    Set them once with the Admin SDK; they ride inside the signed token, so
    no DB lookup is needed on the hot path.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import firebase_admin
from fastapi import Depends, HTTPException, Request
from firebase_admin import auth as fb_auth

log = logging.getLogger("ai-platform.auth")

TIER_RANK = {"free": 0, "pro": 1, "admin": 2}

# Admin allowlist is .env-controlled (comma-separated). Admin access is by
# email identity, not by tier claim — tiers gate features, ADMIN_EMAILS gates
# the control plane. No default: unset means no admins.
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", "").split(",")
    if e.strip()
}

# On Cloud Run, Application Default Credentials resolve automatically from the
# service account. Locally, set GOOGLE_APPLICATION_CREDENTIALS or use
# AUTH_DISABLED=1 for offline dev with Ollama.
if not firebase_admin._apps:
    try:
        # Explicit projectId so ID-token audience checks work under any
        # credential type (user ADC locally, service account on Cloud Run).
        _opts = {"projectId": os.environ["GCP_PROJECT"]} if os.getenv("GCP_PROJECT") else None
        firebase_admin.initialize_app(options=_opts)
    except Exception as exc:  # pragma: no cover - local dev without creds
        log.warning("firebase-admin not initialized (%s); AUTH_DISABLED mode only", exc)


@dataclass(frozen=True)
class AuthedUser:
    uid: str
    email: str | None
    tier: str

    @property
    def is_admin(self) -> bool:
        return bool(self.email) and self.email.lower() in ADMIN_EMAILS


async def verify_firebase_token(request: Request) -> AuthedUser:
    if os.getenv("AUTH_DISABLED") == "1":
        return AuthedUser(uid="local-dev", email=next(iter(ADMIN_EMAILS)), tier="admin")

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")

    try:
        decoded = fb_auth.verify_id_token(header.removeprefix("Bearer "))
    except Exception:
        raise HTTPException(401, "Invalid or expired token")

    return AuthedUser(
        uid=decoded["uid"],
        email=decoded.get("email"),
        tier=decoded.get("tier", "free"),
    )


async def require_admin(user: AuthedUser = Depends(verify_firebase_token)) -> AuthedUser:
    if not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return user


def require_tier(minimum: str):
    """Dependency factory: `Depends(require_tier("pro"))`."""

    async def checker(user: AuthedUser = Depends(verify_firebase_token)) -> AuthedUser:
        if TIER_RANK.get(user.tier, -1) < TIER_RANK[minimum]:
            raise HTTPException(403, f"Requires '{minimum}' tier")
        return user

    return checker
