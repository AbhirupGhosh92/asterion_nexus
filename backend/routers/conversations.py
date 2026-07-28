"""Conversation history — list, read, delete. All scoped by verified uid."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from core.auth import AuthedUser, verify_firebase_token

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(
    request: Request, user: AuthedUser = Depends(verify_firebase_token)
):
    return await request.app.state.store.list_conversations(user.uid)


@router.get("/{cid}")
async def get_conversation(
    cid: str, request: Request, user: AuthedUser = Depends(verify_firebase_token)
):
    messages = await request.app.state.store.get_messages(user.uid, cid)
    if messages is None:
        raise HTTPException(404, "Conversation not found")
    return {"id": cid, "messages": messages}


@router.delete("/{cid}")
async def delete_conversation(
    cid: str, request: Request, user: AuthedUser = Depends(verify_firebase_token)
):
    await request.app.state.store.delete_conversation(user.uid, cid)
    return {"deleted": cid}
