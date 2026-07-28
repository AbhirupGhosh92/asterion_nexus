"""
NEXUS backend — application factory and composition root.

This file does one job: build the object graph once at startup and mount the
routers. No business logic lives here.

Layering (server-side MVVM):

    routers/       View       HTTP in, HTTP out. No decisions.
    services/      ViewModel  Orchestration: what happens on a request.
    repositories/  Model      Data access: Firestore, Storage, Memory Bank.
    providers/     Model      LLMs, Dify, and the guardrail adapters.
    models/        Model      Pydantic schemas shared across layers.
    core/          —          Config and auth used by every layer.

Run: uvicorn app:app --port 8080
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from core import config
from core.auth import AuthedUser, verify_firebase_token
from repositories.chat_repo import ChatStore
from repositories.media_repo import MediaStore
from repositories.memory_repo import MemoryBank
from routers import admin, agents, chat, conversations, uploads
from services.chat_service import ChatService
from services.quota_service import QuotaStore, refund_on_server_error
from services.registry_service import ModelRegistry

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ai-platform")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Admin-managed model catalog. Every chat resolves its model — and that
    # model's guardrail-wrapped instance — through here, gated by tier.
    registry = ModelRegistry(
        project=config.GCP_PROJECT,
        region=config.GCP_REGION,
        guardrails_config_path=config.GUARDRAILS_CONFIG_PATH,
    )
    await registry.seed_default()

    # Dify engine: console client for agent lifecycle, injected into the
    # registry so provider="dify" models resolve to a guarded adapter.
    from providers.dify import DifyClient

    registry.dify = DifyClient(
        base_url=config.DIFY_BASE_URL,
        admin_email=config.DIFY_ADMIN_EMAIL,
        admin_password=config.DIFY_ADMIN_PASSWORD,
    )
    if registry.dify.enabled:
        log.info("Dify engine configured at %s", config.DIFY_BASE_URL)

    store = ChatStore(project=config.GCP_PROJECT)
    media = MediaStore(project=config.GCP_PROJECT, bucket=config.STORAGE_BUCKET)
    memory = MemoryBank(project=config.GCP_PROJECT, region=config.GCP_REGION)
    await memory.connect()

    registry.media = media  # image generation writes through the media store

    app.state.registry = registry
    app.state.store = store
    app.state.media = media
    app.state.memory = memory
    app.state.quota = QuotaStore(project=config.GCP_PROJECT)
    # Raw model used for internal tasks (conversation titling), not for chat.
    app.state.llm = registry.raw_llm() if config.LLM_PROVIDER != "mock" else None
    app.state.chat = ChatService(
        registry=registry, store=store, memory=memory, media=media,
        title_llm=app.state.llm,
    )

    yield

    await memory.close()


app = FastAPI(title="AI Platform API", version="1.0.0", lifespan=lifespan)

# Refund a quota call when a request errors out before doing real work.
app.middleware("http")(refund_on_server_error)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["POST", "GET", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(uploads.router)
app.include_router(agents.router)
app.include_router(admin.router)


# Hosting rewrites only forward /api/**, hence the alias.
@app.get("/healthz")
@app.get("/api/healthz")
async def healthz():
    return {"status": "ok", "provider": config.LLM_PROVIDER}


@app.get("/api/me")
async def me(request: Request, user: AuthedUser = Depends(verify_firebase_token)):
    import asyncio

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
    import os

    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
