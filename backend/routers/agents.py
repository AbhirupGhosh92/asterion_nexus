"""
Specialist agents — /api/agents.

The homepage gallery: every signed-in user sees the full roster of
admin-forged Dify agents, with entries above their tier marked `locked` so
the UI can offer an upgrade rather than pretend they don't exist.

Listing costs no model call, so this depends on plain token verification
rather than `require_quota`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from core.auth import AuthedUser, verify_firebase_token

router = APIRouter(prefix="/api/agents")


@router.get("")
async def list_agents(request: Request, user: AuthedUser = Depends(verify_firebase_token)):
    return await request.app.state.registry.list_agents(user.tier)
