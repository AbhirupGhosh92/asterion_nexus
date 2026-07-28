"""
Admin control plane — /api/admin/*.

Access: ADMIN_EMAILS in .env (see auth.require_admin). Tiers don't grant
admin; identity does.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from firebase_admin import auth as fb_auth
from pydantic import BaseModel, Field

from core.auth import TIER_RANK, AuthedUser, require_admin

log = logging.getLogger("ai-platform.admin")

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
@router.get("/users")
async def list_users(request: Request):
    def _list():
        out = []
        for u in fb_auth.list_users().iterate_all():
            out.append({
                "uid": u.uid,
                "email": u.email,
                "display_name": u.display_name,
                "tier": (u.custom_claims or {}).get("tier", "free"),
                "disabled": u.disabled,
                "created_at": u.user_metadata.creation_timestamp,
                "last_sign_in": u.user_metadata.last_sign_in_timestamp,
            })
        return out

    users = await asyncio.to_thread(_list)

    # Decorate with this period's quota usage / effective limit.
    quota = request.app.state.quota
    if quota.enabled:
        cfg = await quota.get_config()
        used_counts, overrides = await asyncio.gather(
            asyncio.gather(*(quota.used(u["uid"]) for u in users)),
            asyncio.gather(*(quota.override_for(u["uid"]) for u in users)),
        )
        for u, used, override in zip(users, used_counts, overrides):
            u["quota_used"] = used
            u["quota_override"] = override
            u["quota_limit"] = (
                override if override is not None
                else cfg["limits"].get(u["tier"], 0)
            )
    return users


class TierUpdate(BaseModel):
    tier: str


@router.post("/users/{uid}/tier")
async def set_tier(uid: str, body: TierUpdate, admin: AuthedUser = Depends(require_admin)):
    if body.tier not in TIER_RANK:
        raise HTTPException(400, f"tier must be one of {list(TIER_RANK)}")
    await asyncio.to_thread(fb_auth.set_custom_user_claims, uid, {"tier": body.tier})
    log.info("admin %s set tier=%s for uid=%s", admin.email, body.tier, uid)
    return {"uid": uid, "tier": body.tier}


class DisabledUpdate(BaseModel):
    disabled: bool


@router.post("/users/{uid}/disabled")
async def set_disabled(uid: str, body: DisabledUpdate, admin: AuthedUser = Depends(require_admin)):
    if uid == admin.uid:
        raise HTTPException(400, "You can't disable your own account")
    await asyncio.to_thread(fb_auth.update_user, uid, disabled=body.disabled)
    if body.disabled:
        # Invalidate existing refresh tokens so access ends at ID-token expiry.
        await asyncio.to_thread(fb_auth.revoke_refresh_tokens, uid)
    log.info("admin %s set disabled=%s for uid=%s", admin.email, body.disabled, uid)
    return {"uid": uid, "disabled": body.disabled}


# --------------------------------------------------------------------------- #
# Quotas — monthly per-user API call limits
# --------------------------------------------------------------------------- #
class QuotaConfigUpdate(BaseModel):
    enabled: bool | None = None
    limits: dict[str, int] | None = None  # {"free": 5, "pro": 100, "admin": -1}


class QuotaOverrideUpdate(BaseModel):
    limit: int | None = None  # None clears the override; -1 = unlimited


@router.get("/quota")
async def get_quota_config(request: Request):
    return await request.app.state.quota.get_config(fresh=True)


@router.post("/quota")
async def set_quota_config(body: QuotaConfigUpdate, request: Request,
                           admin: AuthedUser = Depends(require_admin)):
    cfg = await request.app.state.quota.set_config(
        enabled=body.enabled, limits=body.limits
    )
    log.info("admin %s updated quota config: %s", admin.email, cfg)
    return cfg


@router.post("/users/{uid}/quota")
async def set_user_quota(uid: str, body: QuotaOverrideUpdate, request: Request,
                         admin: AuthedUser = Depends(require_admin)):
    await request.app.state.quota.set_override(uid, body.limit)
    log.info("admin %s set quota override=%s for uid=%s", admin.email, body.limit, uid)
    return {"uid": uid, "quota_override": body.limit}


@router.post("/users/{uid}/quota/reset")
async def reset_user_quota(uid: str, request: Request,
                           admin: AuthedUser = Depends(require_admin)):
    await request.app.state.quota.reset(uid)
    log.info("admin %s reset quota usage for uid=%s", admin.email, uid)
    return {"uid": uid, "used": 0}


# --------------------------------------------------------------------------- #
# Model registry
# --------------------------------------------------------------------------- #
class ModelSpec(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9\-_.]{1,40}$")
    label: str
    provider: str
    model: str
    min_tier: str = "free"
    enabled: bool = True
    extra: dict = Field(default_factory=dict)


@router.get("/models")
async def list_models(request: Request):
    return await request.app.state.registry.list_all()


@router.post("/models")
async def upsert_model(body: ModelSpec, request: Request, admin: AuthedUser = Depends(require_admin)):
    spec = body.model_dump()
    model_id = spec.pop("id")
    await request.app.state.registry.upsert(model_id, spec)
    log.info("admin %s upserted model %s", admin.email, model_id)
    return {"id": model_id, **spec}


@router.delete("/models/{model_id}")
async def delete_model(model_id: str, request: Request, admin: AuthedUser = Depends(require_admin)):
    await request.app.state.registry.delete(model_id)
    log.info("admin %s deleted model %s", admin.email, model_id)
    return {"deleted": model_id}


# --------------------------------------------------------------------------- #
# Dify agents — built and controlled from the NEXUS UI
# --------------------------------------------------------------------------- #
class AgentSpec(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9\-_.]{1,40}$")
    name: str
    instructions: str
    model: str = "gemini-2.5-flash"
    min_tier: str = "pro"
    tools: list[str] = Field(default_factory=list)
    # Which runtime builds this agent: "langgraph" (in-process deep agent) or
    # "dify" (external engine). They have separate tool catalogs.
    engine: str = "langgraph"


@router.get("/tools")
async def list_tools(request: Request, engine: str = "langgraph"):
    """The tool arsenal for an engine — the two runtimes don't share one."""
    if engine == "langgraph":
        from providers.agent_tools import TOOL_CATALOG as DEEP_CATALOG

        return [
            {"id": k, "label": v["label"], "description": v["description"]}
            for k, v in DEEP_CATALOG.items()
        ]

    from providers.dify import TOOL_CATALOG

    catalog = dict(TOOL_CATALOG)
    dify = request.app.state.registry.dify
    if dify is not None and dify.enabled:
        catalog.update(await dify.mcp_tool_catalog())
    return [
        {"id": k, "label": v["label"], "description": v["description"]}
        for k, v in catalog.items()
    ]


# --------------------------------------------------------------------------- #
# MCP servers — modular tool providers, managed from NEXUS
# --------------------------------------------------------------------------- #
class MCPServerSpec(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9\-_.]{1,40}$")
    server_url: str
    headers: dict[str, str] = Field(default_factory=dict)


def _dify_or_503(request: Request):
    dify = request.app.state.registry.dify
    if dify is None or not dify.enabled:
        raise HTTPException(503, "Dify is not configured")
    return dify


# --------------------------------------------------------------------------- #
# Dify engine — status and lifecycle
# --------------------------------------------------------------------------- #
class EngineAction(BaseModel):
    action: str  # start | stop | restart


@router.get("/engine")
async def engine_status(request: Request):
    import services.engine_service as dify_ops

    return await dify_ops.status(
        request.app.state.registry.dify, request.app.state.registry
    )


@router.post("/engine")
async def engine_control(body: EngineAction, request: Request,
                         admin: AuthedUser = Depends(require_admin)):
    import services.engine_service as dify_ops

    try:
        result = await dify_ops.control(body.action)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    log.info("admin %s ran engine %s -> ok=%s", admin.email, body.action, result["ok"])
    # A restarted engine changes which agents are reachable; drop the cached
    # probe so the next status/model list reflects reality immediately.
    dify = request.app.state.registry.dify
    if dify is not None:
        dify._up_at = 0.0
    return result


@router.get("/mcp")
async def list_mcp_servers(request: Request):
    return await _dify_or_503(request).list_mcp_servers()


@router.post("/mcp")
async def add_mcp_server(body: MCPServerSpec, request: Request,
                         admin: AuthedUser = Depends(require_admin)):
    result = await _dify_or_503(request).add_mcp_server(
        name=body.name, server_url=body.server_url,
        server_identifier=body.name.lower(), headers=body.headers or None,
    )
    log.info("admin %s linked MCP server %s (%d tools)",
             admin.email, body.name, len(result["tools"]))
    return result


@router.delete("/mcp/{provider_id}")
async def delete_mcp_server(provider_id: str, request: Request,
                            admin: AuthedUser = Depends(require_admin)):
    await _dify_or_503(request).delete_mcp_server(provider_id)
    log.info("admin %s removed MCP server %s", admin.email, provider_id)
    return {"deleted": provider_id}


@router.get("/agents")
async def list_agents(request: Request):
    from services.registry_service import AGENT_PROVIDERS

    models = await request.app.state.registry.list_all()
    return [m for m in models if m.get("provider") in AGENT_PROVIDERS]


@router.post("/agents")
async def create_agent(body: AgentSpec, request: Request, admin: AuthedUser = Depends(require_admin)):
    if body.engine == "langgraph":
        # Nothing external to provision: a deep agent is its spec, compiled on
        # first use from the registry entry.
        from providers.agent_tools import TOOL_CATALOG as DEEP_CATALOG

        unknown = [t for t in body.tools if t not in DEEP_CATALOG]
        if unknown:
            raise HTTPException(400, f"Unknown tools for langgraph: {unknown}")
        await request.app.state.registry.upsert(f"agent-{body.id}", {
            "label": f"◈ {body.name}",
            "provider": "langgraph",
            "model": body.model,
            "min_tier": body.min_tier,
            "enabled": True,
            "extra": {"instructions": body.instructions,
                      "tools": ",".join(body.tools)},
        })
        log.info("admin %s created deep agent %s", admin.email, body.id)
        return {"id": f"agent-{body.id}", "engine": "langgraph"}

    dify = request.app.state.registry.dify
    if dify is None or not dify.enabled:
        raise HTTPException(503, "Dify is not configured (DIFY_BASE_URL / admin creds)")

    created = await dify.create_agent(
        name=body.name, instructions=body.instructions, model=body.model,
        description=f"Created from NEXUS by {admin.email}", tools=body.tools,
    )
    await request.app.state.registry.upsert(f"agent-{body.id}", {
        "label": f"⚡ {body.name}",
        "provider": "dify",
        "model": body.model,
        "min_tier": body.min_tier,
        "enabled": True,
        "extra": {"app_id": created["app_id"], "api_key": created["api_key"],
                  "instructions": body.instructions,
                  "tools": ",".join(body.tools)},
    })
    log.info("admin %s created dify agent %s (app %s)", admin.email, body.id, created["app_id"])
    return {"id": f"agent-{body.id}", "app_id": created["app_id"]}


@router.delete("/agents/{model_id}")
async def delete_agent(model_id: str, request: Request, admin: AuthedUser = Depends(require_admin)):
    from services.registry_service import AGENT_PROVIDERS

    registry = request.app.state.registry
    spec = next((m for m in await registry.list_all() if m["id"] == model_id), None)
    if spec is None or spec.get("provider") not in AGENT_PROVIDERS:
        raise HTTPException(404, "Agent not found")

    # A deep agent has no external resource to release; a Dify one owns an app.
    app_id = (spec.get("extra") or {}).get("app_id")
    if spec["provider"] == "dify" and app_id and registry.dify and registry.dify.enabled:
        try:
            await registry.dify.delete_agent(app_id)
        except Exception as exc:
            log.warning("Dify app delete failed (continuing): %s", exc)
    await registry.delete(model_id)
    log.info("admin %s deleted %s agent %s", admin.email, spec["provider"], model_id)
    return {"deleted": model_id}
