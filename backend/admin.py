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

from auth import TIER_RANK, AuthedUser, require_admin

log = logging.getLogger("ai-platform.admin")

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
@router.get("/users")
async def list_users():
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

    return await asyncio.to_thread(_list)


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
    min_tier: str = "free"
    tools: list[str] = Field(default_factory=list)


@router.get("/tools")
async def list_tools(request: Request):
    from dify import TOOL_CATALOG

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
    models = await request.app.state.registry.list_all()
    return [m for m in models if m.get("provider") == "dify"]


@router.post("/agents")
async def create_agent(body: AgentSpec, request: Request, admin: AuthedUser = Depends(require_admin)):
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
    registry = request.app.state.registry
    spec = next((m for m in await registry.list_all() if m["id"] == model_id), None)
    if spec is None or spec.get("provider") != "dify":
        raise HTTPException(404, "Agent not found")
    app_id = (spec.get("extra") or {}).get("app_id")
    if app_id and registry.dify and registry.dify.enabled:
        try:
            await registry.dify.delete_agent(app_id)
        except Exception as exc:
            log.warning("Dify app delete failed (continuing): %s", exc)
    await registry.delete(model_id)
    log.info("admin %s deleted dify agent %s", admin.email, model_id)
    return {"deleted": model_id}
