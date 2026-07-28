"""
Monthly per-user API quotas, admin-controlled.

Limits are per tier (free/pro/admin) with optional per-user overrides, all
stored in Firestore and editable from the admin panel:

  config/quota                 {enabled: bool, limits: {free: 5, pro: …}}
  users/{uid}                  quota_override: int | null   (-1 = unlimited)
  users/{uid}/usage/{YYYY-MM}  {count: n, updated_at}

Usage buckets are keyed by UTC month, so quotas reset automatically at the
start of each month — no cron, no cleanup job.

Enforcement is up front (consume-then-call): a request that trips the limit
never reaches the model. Operators in ADMIN_EMAILS bypass quotas entirely.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from google.cloud import firestore

from core.auth import AuthedUser, verify_firebase_token

log = logging.getLogger("ai-platform.quota")

DEFAULT_LIMITS = {"free": 5, "pro": 100, "admin": -1}  # -1 = unlimited
CONFIG_TTL_SECONDS = 30  # config is read on every guarded call; cache briefly


def current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def next_reset() -> str:
    now = datetime.now(timezone.utc)
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return f"{year}-{month:02d}-01"


class QuotaStore:
    def __init__(self, project: str):
        self._db = firestore.AsyncClient(project=project) if project else None
        self._cfg: dict | None = None
        self._cfg_at: float = 0.0
        if not self._db:
            log.warning("QuotaStore disabled (no GCP_PROJECT) — quotas not enforced")

    @property
    def enabled(self) -> bool:
        return self._db is not None

    def _usage_ref(self, uid: str, period: str | None = None):
        return (
            self._db.collection("users").document(uid)
            .collection("usage").document(period or current_period())
        )

    # ---- config ------------------------------------------------------------

    async def get_config(self, *, fresh: bool = False) -> dict:
        if not self._db:
            return {"enabled": False, "limits": dict(DEFAULT_LIMITS)}
        if not fresh and self._cfg and (time.monotonic() - self._cfg_at) < CONFIG_TTL_SECONDS:
            return self._cfg
        doc = await self._db.collection("config").document("quota").get()
        cfg = doc.to_dict() if doc.exists else None
        if not cfg:
            cfg = {"enabled": True, "limits": dict(DEFAULT_LIMITS)}
            await self._db.collection("config").document("quota").set(cfg)
            log.info("Seeded default quota config: %s", cfg)
        cfg.setdefault("enabled", True)
        cfg["limits"] = {**DEFAULT_LIMITS, **(cfg.get("limits") or {})}
        self._cfg, self._cfg_at = cfg, time.monotonic()
        return cfg

    async def set_config(self, *, enabled: bool | None = None,
                         limits: dict | None = None) -> dict:
        cfg = await self.get_config(fresh=True)
        if enabled is not None:
            cfg["enabled"] = enabled
        if limits:
            for tier, value in limits.items():
                if tier not in DEFAULT_LIMITS:
                    raise HTTPException(400, f"Unknown tier '{tier}'")
                cfg["limits"][tier] = int(value)
        await self._db.collection("config").document("quota").set(cfg)
        self._cfg, self._cfg_at = cfg, time.monotonic()
        return cfg

    # ---- per-user ----------------------------------------------------------

    async def override_for(self, uid: str) -> int | None:
        """Per-user limit that wins over the tier default (None = use tier)."""
        if not self._db:
            return None
        doc = await self._db.collection("users").document(uid).get()
        value = (doc.to_dict() or {}).get("quota_override") if doc.exists else None
        return None if value is None else int(value)

    async def set_override(self, uid: str, limit: int | None) -> None:
        await self._db.collection("users").document(uid).set(
            {"quota_override": None if limit is None else int(limit)}, merge=True
        )

    async def used(self, uid: str, period: str | None = None) -> int:
        if not self._db:
            return 0
        doc = await self._usage_ref(uid, period).get()
        return int((doc.to_dict() or {}).get("count", 0)) if doc.exists else 0

    async def reset(self, uid: str) -> None:
        await self._usage_ref(uid).set(
            {"count": 0, "updated_at": datetime.now(timezone.utc)}
        )

    async def refund(self, uid: str) -> None:
        """Give a call back — used when the platform itself failed (5xx)."""
        if not self._db:
            return
        if await self.used(uid) > 0:
            await self._usage_ref(uid).set(
                {"count": firestore.Increment(-1),
                 "updated_at": datetime.now(timezone.utc)},
                merge=True,
            )

    async def status(self, user: AuthedUser) -> dict:
        """What the UI shows: used / limit / remaining for this period."""
        base = {"period": current_period(), "resets_on": next_reset(), "used": 0}
        if not self._db:
            return {**base, "limit": -1, "remaining": -1, "enforced": False}

        cfg, used, override = await asyncio.gather(
            self.get_config(), self.used(user.uid), self.override_for(user.uid)
        )
        enforced = bool(cfg["enabled"]) and not user.is_admin
        limit = override if override is not None else cfg["limits"].get(user.tier, 0)
        if not enforced:
            limit = -1
        remaining = -1 if limit < 0 else max(0, limit - used)
        return {**base, "used": used, "limit": limit,
                "remaining": remaining, "enforced": enforced}

    # ---- enforcement -------------------------------------------------------

    async def consume(self, user: AuthedUser) -> None:
        """Charge one call, or raise 429. Operators bypass."""
        if not self._db or user.is_admin:
            return
        cfg = await self.get_config()
        if not cfg["enabled"]:
            return

        used, override = await asyncio.gather(
            self.used(user.uid), self.override_for(user.uid)
        )
        limit = override if override is not None else cfg["limits"].get(user.tier, 0)
        if limit < 0:
            return
        if used >= limit:
            raise HTTPException(
                429,
                f"Monthly quota reached ({used}/{limit} calls). "
                f"Resets on {next_reset()}. Ask an admin for a higher limit.",
            )
        await self._usage_ref(user.uid).set(
            {"count": firestore.Increment(1),
             "updated_at": datetime.now(timezone.utc)},
            merge=True,
        )


async def require_quota(
    request: Request, user: AuthedUser = Depends(verify_firebase_token)
) -> AuthedUser:
    """Auth + quota in one dependency, for endpoints that cost real money."""
    await request.app.state.quota.consume(user)
    # Marked so the refund middleware can give the call back on a 5xx.
    request.state.quota_uid = user.uid
    return user


async def refund_on_server_error(request: Request, call_next):
    """
    Charge only for calls that actually ran a model.

    Quota is consumed up front (so nothing slips through under concurrency),
    then refunded if the request errored out before doing any real work — a
    platform 5xx, or a 4xx like "model not available on your tier". 429 is
    excluded because it never consumed anything in the first place.
    """
    response = await call_next(request)
    uid = getattr(request.state, "quota_uid", None)
    if uid and response.status_code >= 400 and response.status_code != 429:
        try:
            await request.app.state.quota.refund(uid)
            log.info("refunded quota call to %s after HTTP %s", uid, response.status_code)
        except Exception as exc:
            log.warning("quota refund failed for %s: %s", uid, exc)
    return response
