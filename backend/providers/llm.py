"""
LLM provider factory — one switch between local dev (free) and prod.

Both return a LangChain chat model, which is what NeMo Guardrails accepts as
its wrapped `llm`. Adding a provider = adding a branch here; nothing else in
the app changes.
"""

from __future__ import annotations

import asyncio
import os


class MockRails:
    """
    Placeholder for LLMRails when no real model is configured
    (LLM_PROVIDER=mock). Same interface as nemoguardrails.LLMRails, so the
    route code is identical — swap to Gemini by setting LLM_PROVIDER=vertexai.
    """

    _REPLY = (
        "[mock LLM] I received your message: \"{last}\". "
        "The full pipeline (auth → guardrails → LLM → memory) is wired; "
        "set LLM_PROVIDER=vertexai to talk to Gemini."
    )

    def _reply_for(self, messages: list[dict]) -> str:
        last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return self._REPLY.format(last=last[:200])

    async def generate_async(self, messages: list[dict]) -> dict:
        return {"role": "assistant", "content": self._reply_for(messages)}

    async def stream_async(self, messages: list[dict]):
        for word in self._reply_for(messages).split(" "):
            yield word + " "
            await asyncio.sleep(0.03)  # simulate token latency for UI work


def build_chat_llm(provider: str, *, project: str = "", region: str = "us-central1"):
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            model=os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
            temperature=0.7,
        )

    if provider == "vertexai":
        from langchain_google_vertexai import ChatVertexAI

        return ChatVertexAI(
            model_name=os.getenv("VERTEX_MODEL", "gemini-2.5-flash"),
            project=project,
            location=region,
            temperature=0.7,
            max_output_tokens=4096,
        )

    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r} (use 'ollama' or 'vertexai')")
