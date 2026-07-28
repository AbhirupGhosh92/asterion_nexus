"""
Vertex AI Memory Bank wrapper (Agent Engine Memory Bank).

Long-term, per-user memory: the platform extracts durable facts from
conversations and recalls them by similarity search, scoped to a user.

Scope discipline (this is the ReBAC boundary):
  - Every read/write is scoped by {"user_id": <verified uid>}.
  - The uid always comes from the verified Firebase token, never from client
    input, so cross-user recall is structurally impossible.

Degrades to a no-op when GCP is unavailable (local Ollama dev) so the app
runs offline without branches in the route code.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("ai-platform.memory")


class MemoryBank:
    def __init__(self, project: str, region: str):
        self.project = project
        self.region = region
        self._client = None
        self._engine_name: str | None = None

    async def connect(self) -> None:
        if not self.project:
            log.info("Memory Bank disabled (no GCP_PROJECT — local dev mode)")
            return
        try:
            import vertexai

            client = vertexai.Client(project=self.project, location=self.region)
            # One Agent Engine instance acts as the memory store for the
            # whole platform; per-user isolation happens via scope, below.
            engines = list(client.agent_engines.list())
            engine = engines[0] if engines else client.agent_engines.create()
            self._engine_name = engine.api_resource.name
            self._client = client
            log.info("Memory Bank connected: %s", self._engine_name)
        except Exception as exc:
            log.warning("Memory Bank unavailable, continuing without it: %s", exc)

    async def retrieve(self, *, user_id: str, query: str, top_k: int = 5) -> list[str]:
        if not self._client:
            return []
        try:
            result = await asyncio.to_thread(
                self._client.agent_engines.retrieve_memories,
                name=self._engine_name,
                scope={"user_id": user_id},
                similarity_search_params={"search_query": query, "top_k": top_k},
            )
            return [m.memory.fact for m in result]
        except Exception as exc:
            log.warning("Memory retrieve failed: %s", exc)
            return []

    async def store(
        self,
        *,
        user_id: str,
        messages: list[dict],
        conversation_id: str | None = None,
    ) -> None:
        """Let Memory Bank extract durable facts from the latest exchange."""
        if not self._client:
            return
        try:
            await asyncio.to_thread(
                self._client.agent_engines.generate_memories,
                name=self._engine_name,
                direct_contents_source={
                    "events": [
                        {"content": {"role": m["role"], "parts": [{"text": m["content"]}]}}
                        for m in messages
                    ]
                },
                scope={"user_id": user_id},
            )
        except Exception as exc:
            log.warning("Memory store failed: %s", exc)

    async def close(self) -> None:
        self._client = None
