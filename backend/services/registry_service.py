"""
LLM model registry — admin-managed, Firestore-backed.

Admins register models from any provider; users pick one per chat, gated by
tier. Each model gets its own NeMo-Guardrails-wrapped instance, built lazily
and cached — the SAME rails config governs every provider.

Firestore: collection `models`, doc id = model key.
  {label, provider, model, min_tier, enabled, extra{...}, created_at}
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import HTTPException
from google.cloud import firestore

from core.auth import TIER_RANK
from providers.llm import MockRails, build_chat_llm

log = logging.getLogger("ai-platform.models")

PROVIDERS = ("vertexai", "ollama", "mock", "dify", "langgraph", "vertexai_image")

# The two agent runtimes. `dify` runs in an external engine; `langgraph` is a
# deep agent built in-process (providers/deep_agents.py). Both answer to the
# same rails contract, so everything below treats them together.
AGENT_PROVIDERS = ("dify", "langgraph")

# Specialist agents are a Pro capability. A per-agent min_tier can raise the
# bar (admin-only agents) but never lower it — so the homepage gallery and the
# composer's model list can't disagree about who may run one.
AGENT_FLOOR_TIER = "pro"


def effective_min_tier(spec: dict) -> str:
    """The tier actually required for a model, applying the agent floor."""
    min_tier = spec.get("min_tier", "free")
    if spec.get("provider") not in AGENT_PROVIDERS:
        return min_tier
    return min_tier if TIER_RANK.get(min_tier, 0) > TIER_RANK[AGENT_FLOOR_TIER] else AGENT_FLOOR_TIER


class ModelRegistry:
    def __init__(self, project: str, region: str, guardrails_config_path: str):
        self.project = project
        self.region = region
        self._db = firestore.AsyncClient(project=project) if project else None
        self._rails_cache: dict[str, object] = {}
        self._rails_config = None
        self._guardrails_path = guardrails_config_path
        self.dify = None  # DifyClient, injected at startup when configured
        self.media = None  # MediaStore, injected at startup (image generation)

    # ---- catalog -----------------------------------------------------------

    async def seed_default(self) -> None:
        """First boot: register the env-configured model so chat works."""
        if not self._db:
            return
        existing = [d async for d in self._db.collection("models").limit(1).stream()]
        if existing:
            return
        provider = os.getenv("LLM_PROVIDER", "mock")
        model = os.getenv("VERTEX_MODEL", "gemini-2.5-flash") if provider == "vertexai" else \
            os.getenv("OLLAMA_MODEL", "llama3.1:8b") if provider == "ollama" else "mock"
        await self._db.collection("models").document("default").set({
            "label": "Gemini 2.5 Flash" if provider == "vertexai" else model,
            "provider": provider,
            "model": model,
            "min_tier": "free",
            "enabled": True,
            "extra": {},
            "created_at": datetime.now(timezone.utc),
        })
        log.info("Seeded default model: %s/%s", provider, model)

    async def list_all(self) -> list[dict]:
        if not self._db:
            return [{"id": "default", "label": "mock", "provider": "mock", "model": "mock",
                     "min_tier": "free", "enabled": True, "extra": {}}]
        out = []
        async for doc in self._db.collection("models").stream():
            d = doc.to_dict()
            d["id"] = doc.id
            d.pop("created_at", None)
            out.append(d)
        return sorted(out, key=lambda d: d["id"])

    async def list_for_tier(self, tier: str) -> list[dict]:
        rank = TIER_RANK.get(tier, 0)
        # Hide Dify agents whenever the engine isn't actually reachable (not
        # deployed, or stopped locally) instead of failing at chat time.
        dify_up = self.dify is not None and await self.dify.is_up()
        return [
            {"id": m["id"], "label": m["label"], "provider": m["provider"]}
            for m in await self.list_all()
            if m.get("enabled")
            and rank >= TIER_RANK.get(effective_min_tier(m), 0)
            and (m.get("provider") != "dify" or dify_up)
        ]

    async def list_agents(self, tier: str) -> list[dict]:
        """The specialist-agent roster for the homepage gallery.

        Unlike `list_for_tier`, this deliberately does NOT hide agents above
        the caller's tier — free users are meant to see what Pro unlocks, so
        each entry carries a `locked` flag instead of vanishing. That is a
        display hint only: `get_rails` still 403s on a locked id, so forging
        `locked: false` client-side buys nothing.
        """
        rank = TIER_RANK.get(tier, 0)
        dify_up = self.dify is not None and await self.dify.is_up()
        out = []
        for m in await self.list_all():
            if m.get("provider") not in AGENT_PROVIDERS or not m.get("enabled"):
                continue
            # Deep agents run in this process, so they are online whenever the
            # backend is; only Dify agents depend on a reachable engine.
            online = dify_up if m["provider"] == "dify" else True
            extra = m.get("extra") or {}
            min_tier = effective_min_tier(m)
            brief = (extra.get("instructions") or "").strip()
            out.append({
                "id": m["id"],
                "label": m["label"],
                # The system prompt doubles as the card blurb; cap it so a
                # long one doesn't bloat every homepage load.
                "description": brief[:400] + ("…" if len(brief) > 400 else ""),
                "tools": [t for t in (extra.get("tools") or "").split(",") if t],
                "min_tier": min_tier,
                "locked": rank < TIER_RANK.get(min_tier, 0),
                "online": online,
                "engine": m["provider"],  # dify | langgraph
            })
        return out

    async def upsert(self, model_id: str, spec: dict) -> None:
        if spec.get("provider") not in PROVIDERS:
            raise HTTPException(400, f"provider must be one of {PROVIDERS}")
        if spec.get("min_tier") not in TIER_RANK:
            raise HTTPException(400, f"min_tier must be one of {list(TIER_RANK)}")
        await self._db.collection("models").document(model_id).set(
            {**spec, "created_at": datetime.now(timezone.utc)}, merge=True
        )
        self._rails_cache.pop(model_id, None)  # rebuild on next use

    async def delete(self, model_id: str) -> None:
        await self._db.collection("models").document(model_id).delete()
        self._rails_cache.pop(model_id, None)

    # ---- resolution --------------------------------------------------------

    async def get_rails(self, model_id: str | None, tier: str):
        """(rails, raw_llm) for this model, enforcing tier access.

        `rails` handles text turns; `raw_llm` (None for mock) is used by the
        hybrid multimodal path, which still runs input/output rails around it.
        """
        allowed = await self.list_for_tier(tier)
        if not allowed:
            raise HTTPException(503, "No models available")
        if model_id is None:
            # Default to the seeded plain-LLM entry; never silently pick an
            # agent or an image model just because it sorts first.
            plain = [m for m in allowed if m["provider"] in ("vertexai", "ollama", "mock")]
            model_id = next(
                (m["id"] for m in plain if m["id"] == "default"),
                (plain or allowed)[0]["id"],
            )
        if model_id not in {m["id"] for m in allowed}:
            raise HTTPException(403, f"Model '{model_id}' not available on your tier")

        if model_id in self._rails_cache:
            return self._rails_cache[model_id]

        spec = next(m for m in await self.list_all() if m["id"] == model_id)
        pair = self._build_rails(spec)
        self._rails_cache[model_id] = pair
        return pair

    def _build_rails(self, spec: dict):
        if spec["provider"] == "mock":
            return MockRails(), None
        from nemoguardrails import LLMRails, RailsConfig

        if self._rails_config is None:
            self._rails_config = RailsConfig.from_path(self._guardrails_path)

        if spec["provider"] in ("dify", "langgraph", "vertexai_image"):
            # Screening rails run on the platform's default Vertex model.
            screen_llm = build_chat_llm("vertexai", project=self.project, region=self.region)
            screen_rails = LLMRails(self._rails_config, llm=screen_llm)

            if spec["provider"] == "dify":
                from providers.dify import DifyRails

                if self.dify is None or not self.dify.enabled:
                    raise HTTPException(503, "Dify is not configured")
                extra = spec.get("extra") or {}
                return DifyRails(self.dify, extra["api_key"], screen_rails), None

            if spec["provider"] == "langgraph":
                from providers.deep_agents import DeepAgentRails, build_agent

                extra = spec.get("extra") or {}
                # The agent's own model, not the screening one: a deep agent
                # may reason on a bigger model than the rails need. Passed
                # explicitly so it can't leak into the next model built.
                agent_llm = build_chat_llm(
                    "vertexai", project=self.project, region=self.region,
                    model=spec["model"],
                )
                agent = build_agent(
                    llm=agent_llm,
                    instructions=extra.get("instructions", ""),
                    tools=[t for t in (extra.get("tools") or "").split(",") if t],
                )
                log.info("Built deep agent %s (%s)", spec["id"], spec["model"])
                return DeepAgentRails(agent, screen_rails), None

            from providers.image_rails import ImageGenRails

            if self.media is None or not self.media.enabled:
                raise HTTPException(503, "Media storage not configured")
            return ImageGenRails(
                project=self.project, region=self.region, model=spec["model"],
                screen_rails=screen_rails, media_store=self.media,
            ), None

        extra = spec.get("extra") or {}
        if extra.get("base_url"):
            os.environ["OLLAMA_BASE_URL"] = extra["base_url"]
        if spec["provider"] == "vertexai":
            os.environ["VERTEX_MODEL"] = spec["model"]
        elif spec["provider"] == "ollama":
            os.environ["OLLAMA_MODEL"] = spec["model"]

        llm = build_chat_llm(spec["provider"], project=self.project, region=self.region)
        log.info("Built rails for model %s (%s/%s)", spec["id"], spec["provider"], spec["model"])
        return LLMRails(self._rails_config, llm=llm), llm

    def raw_llm(self, model_id: str | None = None):
        """Unwrapped LLM for internal tasks (titling). Vertex default."""
        try:
            return build_chat_llm("vertexai", project=self.project, region=self.region) \
                if self.project else None
        except Exception:
            return None
