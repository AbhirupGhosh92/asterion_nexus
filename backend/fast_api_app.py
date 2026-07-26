"""
AI Platform — Backend entry point.

FastAPI server that:
  1. Verifies Firebase Auth ID tokens (identity + RBAC via custom claims)
  2. Wraps every LLM call with NVIDIA NeMo Guardrails (input + output rails)
  3. Connects to Vertex AI Memory Bank for long-term, per-user memory
  4. Swaps between Vertex AI (prod) and Ollama (local dev) via LLM_PROVIDER
  5. Propagates the originating user's identity to downstream services (Dify)

Run locally:
    LLM_PROVIDER=ollama uvicorn fast_api_app:app --reload --port 8080
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth import AuthedUser, require_tier, verify_firebase_token
from memory import MemoryBank
from models_registry import ModelRegistry
from quota import QuotaStore, refund_on_server_error, require_quota
from store import ChatStore
from uploads import MediaStore

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ai-platform")

# --------------------------------------------------------------------------- #
# Configuration (env-driven; see .env.example)
# --------------------------------------------------------------------------- #
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")  # "vertexai" | "ollama"
GCP_PROJECT = os.getenv("GCP_PROJECT", "")
GCP_REGION = os.getenv("GCP_REGION", "us-central1")
GUARDRAILS_CONFIG_PATH = os.getenv("GUARDRAILS_CONFIG_PATH", "guardrails")
DIFY_BASE_URL = os.getenv("DIFY_BASE_URL", "")  # optional orchestration layer
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", f"{GCP_PROJECT}.firebasestorage.app" if GCP_PROJECT else "")


# --------------------------------------------------------------------------- #
# Lifespan: build the LLM, wrap it in NeMo Guardrails, connect Memory Bank.
# Heavy objects are created once per container, not per request.
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Admin-managed model registry: every chat resolves its model (and its
    # guardrails-wrapped instance) through this, gated by user tier.
    app.state.registry = ModelRegistry(
        project=GCP_PROJECT, region=GCP_REGION,
        guardrails_config_path=GUARDRAILS_CONFIG_PATH,
    )
    await app.state.registry.seed_default()

    # Dify engine (self-hosted): console client for agent lifecycle,
    # injected into the registry for provider="dify" model resolution.
    from dify import DifyClient

    app.state.registry.dify = DifyClient(
        base_url=DIFY_BASE_URL,
        admin_email=os.getenv("DIFY_ADMIN_EMAIL", ""),
        admin_password=os.getenv("DIFY_ADMIN_PASSWORD", ""),
    )
    if app.state.registry.dify.enabled:
        log.info("Dify engine configured at %s", DIFY_BASE_URL)

    # Raw model for internal tasks (conversation titling).
    app.state.llm = app.state.registry.raw_llm() if LLM_PROVIDER != "mock" else None

    # Firestore: user profiles + per-conversation chat history.
    app.state.store = ChatStore(project=GCP_PROJECT)

    # Firebase Storage: image/audio/video uploads + generated images.
    app.state.media = MediaStore(project=GCP_PROJECT, bucket=STORAGE_BUCKET)
    app.state.registry.media = app.state.media

    # Monthly per-user API quotas (admin-configurable).
    app.state.quota = QuotaStore(project=GCP_PROJECT)

    # Vertex AI Memory Bank — no-ops gracefully when not on GCP (local dev).
    app.state.memory = MemoryBank(project=GCP_PROJECT, region=GCP_REGION)
    await app.state.memory.connect()

    yield

    await app.state.memory.close()


app = FastAPI(title="AI Platform API", version="0.1.0", lifespan=lifespan)

from admin import router as admin_router  # noqa: E402
from uploads import router as uploads_router  # noqa: E402

app.include_router(admin_router)
app.include_router(uploads_router)

app.middleware("http")(refund_on_server_error)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["POST", "GET"],
    allow_headers=["Authorization", "Content-Type"],
)


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant|system)$")
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    conversation_id: str | None = None
    use_memory: bool = True
    model: str | None = None          # registry model id; None = default
    attachments: list[str] = []       # upload ids attached to the last message


class AgentStep(BaseModel):
    position: int = 0
    thought: str | None = None
    tool: str | None = None
    tool_input: str | None = None
    observation: str | None = None


class ChatResponse(BaseModel):
    content: str
    conversation_id: str | None
    guardrail_triggered: bool = False
    steps: list[AgentStep] = []  # agent decision trace, when a model has one


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/healthz")
@app.get("/api/healthz")  # alias reachable through the /api/** Hosting rewrite
async def healthz():
    return {"status": "ok", "provider": LLM_PROVIDER}


async def _prepend_memories(memory: MemoryBank, uid: str, messages: list[dict]) -> None:
    # Retrieve long-term memories scoped to THIS user only. The memory scope
    # is derived from the verified token, never from the request body — a
    # user can never read another user's memories (ReBAC: owner-of edge).
    memories = await memory.retrieve(user_id=uid, query=messages[-1]["content"])
    if memories:
        messages.insert(0, {
            "role": "system",
            "content": "Relevant things you remember about this user:\n" + "\n".join(memories),
        })


async def _attach_media(state, uid: str, messages: list[dict], upload_ids: list[str]) -> None:
    """
    Convert the last user message to multimodal content parts, pulling the
    user's OWN uploads only (uid-scoped lookup — attachment ids from other
    users simply don't resolve).
    """
    import base64

    parts = []
    for fid in upload_ids[:5]:
        found = await state.media.get(uid, fid)
        if not found:
            continue
        meta, data = found
        b64 = base64.b64encode(data).decode()
        if meta["content_type"].startswith("image/"):
            # OpenAI-style data URI — understood by both NeMo Guardrails'
            # multimodal passthrough and ChatVertexAI.
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{meta['content_type']};base64,{b64}"},
            })
        else:
            # audio/video: LangChain media part (Vertex-native)
            parts.append({
                "type": "media",
                "mime_type": meta["content_type"],
                "data": b64,
            })
    if parts:
        messages[-1] = {
            "role": "user",
            "content": [{"type": "text", "text": messages[-1]["content"]}, *parts],
        }


REFUSAL_TEXT = "I can't help with that"


def _text_of(content) -> str:
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if p.get("type") == "text")
    return content


async def _guarded_multimodal(rails, llm, messages: list[dict]) -> tuple[str, bool]:
    """
    Hybrid guardrail path for multimodal turns. NeMo's full pipeline drops
    media parts, so we run the stages explicitly:
      1. INPUT rails on the text (attack → refusal, model never called)
      2. raw multimodal LLM call with the media parts intact
      3. OUTPUT rails on the generated text (leak → refusal)
    Returns (content, guardrail_triggered).
    """
    text_msgs = [{"role": m["role"], "content": _text_of(m["content"])} for m in messages]

    checked = await rails.generate_async(messages=text_msgs, options={"rails": ["input"]})
    inp = checked.response[0]["content"]
    if REFUSAL_TEXT in inp:
        return inp, True

    resp = await llm.ainvoke(messages)
    content = resp.content if isinstance(resp.content, str) else str(resp.content)

    out = await rails.generate_async(
        messages=text_msgs + [{"role": "assistant", "content": content}],
        options={"rails": ["output"]},
    )
    final = out.response[0]["content"]
    return final, REFUSAL_TEXT in final


async def _make_title(app_state, first_message: str) -> str:
    """ChatGPT-style short topic title for a new conversation."""
    fallback = first_message.strip()[:48] or "New chat"
    if app_state.llm is None:
        return fallback
    try:
        resp = await app_state.llm.ainvoke(
            [{
                "role": "user",
                "content": (
                    "Write a title (3-6 words, no quotes, no punctuation at the "
                    "end) summarizing the topic of this message:\n\n" + first_message[:500]
                ),
            }]
        )
        title = (resp.content or "").strip().strip('"')
        return title[:60] or fallback
    except Exception as exc:
        log.warning("Title generation failed: %s", exc)
        return fallback


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
    user: AuthedUser = Depends(require_quota),
):
    """Guarded chat completion with per-user long-term memory + history."""
    state = request.app.state
    rails, raw_llm = await state.registry.get_rails(body.model, user.tier)
    messages = [m.model_dump() for m in body.messages]
    user_text = messages[-1]["content"]

    if body.use_memory:
        await _prepend_memories(state.memory, user.uid, messages)
    if body.attachments and state.media.enabled:
        await _attach_media(state, user.uid, messages, body.attachments)

    steps: list[dict] = []
    multimodal = isinstance(messages[-1]["content"], list) and raw_llm is not None
    if multimodal:
        content, guardrail_triggered = await _guarded_multimodal(rails, raw_llm, messages)
    elif getattr(rails, "needs_user", False):
        # Dify agent / image generation: same rail stages, the engine call
        # carries the requesting user's id for scoping and attribution.
        result = await rails.generate_async(messages, user_id=user.uid)
        content = result["content"]
        steps = result.get("steps", [])
        guardrail_triggered = REFUSAL_TEXT in content
    else:
        # All input/output flows through NeMo Guardrails. If an input rail
        # refuses, the configured bot refusal message comes back instead of a
        # model completion — the raw LLM is never exposed.
        result = await rails.generate_async(messages=messages)
        content = result["content"] if isinstance(result, dict) else str(result)
        guardrail_triggered = REFUSAL_TEXT in content

    cid = body.conversation_id
    if state.store.enabled:
        await state.store.ensure_user(user.uid, user.email, user.tier)
        if cid is None:
            cid = await state.store.create_conversation(
                user.uid, await _make_title(state, user_text)
            )
        await state.store.append_exchange(user.uid, cid, user_text, content, steps=steps)

    if body.use_memory and not guardrail_triggered:
        await state.memory.store(
            user_id=user.uid,
            conversation_id=cid,
            messages=[{"role": "user", "content": user_text}, {"role": "assistant", "content": content}],
        )

    return ChatResponse(
        content=content, conversation_id=cid,
        guardrail_triggered=guardrail_triggered, steps=steps,
    )


@app.post("/api/chat/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    user: AuthedUser = Depends(require_quota),
):
    """
    SSE streaming with history persistence. Events are JSON:
      {"type":"meta","conversation_id":...}   first — client learns the id
      {"type":"token","text":...}             guarded output chunks
      {"type":"title","title":...}            only for a new conversation
      {"type":"done"}
    """
    import json

    state = request.app.state
    rails, raw_llm = await state.registry.get_rails(body.model, user.tier)
    messages = [m.model_dump() for m in body.messages]
    user_text = messages[-1]["content"]

    if body.use_memory:
        await _prepend_memories(state.memory, user.uid, messages)
    if body.attachments and state.media.enabled:
        await _attach_media(state, user.uid, messages, body.attachments)
    multimodal = isinstance(messages[-1]["content"], list) and raw_llm is not None

    async def event_source():
        cid = body.conversation_id
        new_conversation = cid is None
        steps: list[dict] = []
        if state.store.enabled:
            await state.store.ensure_user(user.uid, user.email, user.tier)
            if new_conversation:
                # Placeholder title now; real title after the exchange.
                cid = await state.store.create_conversation(user.uid, user_text[:48] or "New chat")
        yield f"data: {json.dumps({'type': 'meta', 'conversation_id': cid})}\n\n"

        if multimodal:
            # Guarded non-streaming call, emitted in chunks for a live feel.
            content, guardrail_triggered = await _guarded_multimodal(rails, raw_llm, messages)
            for i in range(0, len(content), 24):
                yield f"data: {json.dumps({'type': 'token', 'text': content[i:i + 24]})}\n\n"
        elif getattr(rails, "needs_user", False):
            # Agents stream their decisions as they make them; image gen and
            # older paths just yield plain text.
            full = []
            async for item in rails.stream_async(messages, user_id=user.uid):
                if isinstance(item, dict) and item.get("kind") == "step":
                    step = item["step"]
                    steps.append(step)
                    yield f"data: {json.dumps({'type': 'step', 'step': step})}\n\n"
                    continue
                text = item["text"] if isinstance(item, dict) else item
                full.append(text)
                yield f"data: {json.dumps({'type': 'token', 'text': text})}\n\n"
            content = "".join(full)
            guardrail_triggered = REFUSAL_TEXT in content
        else:
            full: list[str] = []
            async for chunk in rails.stream_async(messages=messages):
                full.append(chunk)
                yield f"data: {json.dumps({'type': 'token', 'text': chunk})}\n\n"
            content = "".join(full)
            guardrail_triggered = REFUSAL_TEXT in content

        if state.store.enabled and cid:
            await state.store.append_exchange(user.uid, cid, user_text, content, steps=steps)
            if new_conversation:
                title = await _make_title(state, user_text)
                await state.store.set_title(user.uid, cid, title)
                yield f"data: {json.dumps({'type': 'title', 'title': title})}\n\n"

        if body.use_memory and not guardrail_triggered:
            await state.memory.store(
                user_id=user.uid,
                conversation_id=cid,
                messages=[{"role": "user", "content": user_text}, {"role": "assistant", "content": content}],
            )

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


# --------------------------------------------------------------------------- #
# Conversation history (ChatGPT-style topics sidebar)
# --------------------------------------------------------------------------- #
@app.get("/api/conversations")
async def list_conversations(
    request: Request, user: AuthedUser = Depends(verify_firebase_token)
):
    return await request.app.state.store.list_conversations(user.uid)


@app.get("/api/conversations/{cid}")
async def get_conversation(
    cid: str, request: Request, user: AuthedUser = Depends(verify_firebase_token)
):
    messages = await request.app.state.store.get_messages(user.uid, cid)
    if messages is None:
        raise HTTPException(404, "Conversation not found")
    return {"id": cid, "messages": messages}


@app.delete("/api/conversations/{cid}")
async def delete_conversation(
    cid: str, request: Request, user: AuthedUser = Depends(verify_firebase_token)
):
    await request.app.state.store.delete_conversation(user.uid, cid)
    return {"deleted": cid}


@app.post("/api/workflows/{workflow_id}/run")
async def run_workflow(
    workflow_id: str,
    body: dict,
    user: AuthedUser = Depends(require_tier("pro")),
):
    """
    Proxy to the Dify orchestration layer (visual workflows / RAG pipelines).

    Identity propagation: the originating user's uid and tier travel with the
    request so downstream tools act with the USER's permissions, not the
    service account's. Dify's `user` field + custom inputs carry the context.
    """
    if not DIFY_BASE_URL:
        raise HTTPException(503, "Orchestration layer not configured")

    import httpx

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{DIFY_BASE_URL}/v1/workflows/run",
            headers={
                "Authorization": f"Bearer {os.environ['DIFY_API_KEY']}",
                # Propagated identity — downstream MCP tools / connectors must
                # check these instead of running as an omnipotent service.
                "X-Acting-User-Id": user.uid,
                "X-Acting-User-Tier": user.tier,
            },
            json={
                "workflow_id": workflow_id,
                "inputs": body,
                "user": user.uid,  # Dify end-user attribution
                "response_mode": "blocking",
            },
        )
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"Workflow error: {resp.text[:500]}")
    return resp.json()


@app.get("/api/me")
async def me(request: Request, user: AuthedUser = Depends(verify_firebase_token)):
    models, quota = await asyncio.gather(
        request.app.state.registry.list_for_tier(user.tier),
        request.app.state.quota.status(user),
    )
    return {
        "uid": user.uid,
        "email": user.email,
        "tier": user.tier,
        "is_admin": user.is_admin,
        "models": models,
        "quota": quota,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("fast_api_app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
