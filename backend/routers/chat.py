"""Chat endpoints — HTTP only; the thinking lives in services/chat_service."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from core.auth import AuthedUser
from models.chat import ChatRequest, ChatResponse
from services.quota_service import require_quota

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
    # require_quota = auth + monthly quota. Never use bare token verification
    # on a model-calling route, or the call is uncapped.
    user: AuthedUser = Depends(require_quota),
):
    return await request.app.state.chat.generate(body, user)


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    user: AuthedUser = Depends(require_quota),
):
    # Awaited so model resolution (and its 403) happens before the response
    # starts; the service returns the frame generator.
    frames = await request.app.state.chat.stream(body, user)
    return StreamingResponse(frames, media_type="text/event-stream")
