"""
Chat orchestration — the "ViewModel" of a conversation turn.

Everything that decides *what happens* on a turn lives here: model
resolution, memory recall, attachment handling, which guardrail path to take,
persistence and title generation. The routers above only translate HTTP.

Three guarded paths, because one size does not fit all:

  text        NeMo Guardrails end to end (input rails → model → output rails)
  multimodal  staged rails, because NeMo drops media parts (see _guarded_multimodal)
  needs_user  Dify agents and image generation, which need the caller's uid
"""

from __future__ import annotations

import json
import logging

from core.config import ASK_PROTOCOL, REFUSAL_TEXT
from models.chat import ChatRequest, ChatResponse

log = logging.getLogger("ai-platform.chat")


def text_of(content) -> str:
    """Flatten a possibly-multimodal content field down to its text."""
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if p.get("type") == "text")
    return content


class ChatService:
    """Bound to app state (registry, store, memory, media) once at startup."""

    def __init__(self, registry, store, memory, media, title_llm=None):
        self.registry = registry
        self.store = store
        self.memory = memory
        self.media = media
        self.title_llm = title_llm

    # ---- helpers ----------------------------------------------------------

    async def _prepend_memories(self, uid: str, messages: list[dict]) -> None:
        """
        Recall long-term memories for THIS user only. The scope comes from the
        verified token, never from the request body, so cross-user recall is
        structurally impossible (ReBAC: owner-of edge).
        """
        memories = await self.memory.retrieve(user_id=uid, query=messages[-1]["content"])
        if memories:
            messages.insert(0, {
                "role": "system",
                "content": "Relevant things you remember about this user:\n"
                           + "\n".join(memories),
            })

    async def _attach_media(self, uid: str, messages: list[dict],
                            upload_ids: list[str]) -> None:
        """
        Turn the last user message into multimodal parts, resolving only the
        caller's OWN uploads — ids belonging to other users simply don't
        resolve, so attachments can't be used to read across accounts.
        """
        import base64

        parts = []
        for fid in upload_ids[:5]:
            found = await self.media.get(uid, fid)
            if not found:
                continue
            meta, data = found
            b64 = base64.b64encode(data).decode()
            if meta["content_type"].startswith("image/"):
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{meta['content_type']};base64,{b64}"},
                })
            else:  # audio/video — LangChain media part (Vertex-native)
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

    async def _guarded_multimodal(self, rails, llm, messages: list[dict]) -> tuple[str, bool]:
        """
        Staged rails for turns carrying media. NeMo's full pipeline strips
        media parts, so the stages run explicitly:
          1. INPUT rails on the text  (attack → refusal, model never called)
          2. raw multimodal call with the media intact
          3. OUTPUT rails on the result (leak → refusal)
        """
        text_msgs = [{"role": m["role"], "content": text_of(m["content"])} for m in messages]

        checked = await rails.generate_async(messages=text_msgs, options={"rails": ["input"]})
        inp = checked.response[0]["content"]
        if REFUSAL_TEXT in inp:
            return inp, True

        resp = await llm.ainvoke([{"role": "system", "content": ASK_PROTOCOL}, *messages])
        content = resp.content if isinstance(resp.content, str) else str(resp.content)

        out = await rails.generate_async(
            messages=text_msgs + [{"role": "assistant", "content": content}],
            options={"rails": ["output"]},
        )
        final = out.response[0]["content"]
        return final, REFUSAL_TEXT in final

    async def _make_title(self, first_message: str) -> str:
        """ChatGPT-style short topic title for a brand-new conversation."""
        fallback = first_message.strip()[:48] or "New chat"
        if self.title_llm is None:
            return fallback
        try:
            resp = await self.title_llm.ainvoke([{
                "role": "user",
                "content": ("Write a title (3-6 words, no quotes, no punctuation "
                            "at the end) summarizing the topic of this message:\n\n"
                            + first_message[:500]),
            }])
            return ((resp.content or "").strip().strip('"'))[:60] or fallback
        except Exception as exc:
            log.warning("Title generation failed: %s", exc)
            return fallback

    async def _prepare(self, body: ChatRequest, user):
        """Shared setup for both the blocking and streaming paths."""
        rails, raw_llm = await self.registry.get_rails(body.model, user.tier)
        messages = [m.model_dump() for m in body.messages]
        if body.use_memory:
            await self._prepend_memories(user.uid, messages)
        if body.attachments and self.media.enabled:
            await self._attach_media(user.uid, messages, body.attachments)
        multimodal = isinstance(messages[-1]["content"], list) and raw_llm is not None
        return rails, raw_llm, messages, multimodal

    async def _remember(self, user, cid, user_text: str, content: str) -> None:
        await self.memory.store(
            user_id=user.uid, conversation_id=cid,
            messages=[{"role": "user", "content": user_text},
                      {"role": "assistant", "content": content}],
        )

    # ---- blocking turn ----------------------------------------------------

    async def generate(self, body: ChatRequest, user) -> ChatResponse:
        rails, raw_llm, messages, multimodal = await self._prepare(body, user)
        user_text = messages[-1]["content"]
        steps: list[dict] = []

        if multimodal:
            content, triggered = await self._guarded_multimodal(rails, raw_llm, messages)
        elif getattr(rails, "needs_user", False):
            result = await rails.generate_async(messages, user_id=user.uid)
            content = result["content"]
            steps = result.get("steps", [])
            triggered = REFUSAL_TEXT in content
        else:
            result = await rails.generate_async(messages=messages)
            content = result["content"] if isinstance(result, dict) else str(result)
            triggered = REFUSAL_TEXT in content

        cid = body.conversation_id
        if self.store.enabled:
            await self.store.ensure_user(user.uid, user.email, user.tier)
            if cid is None:
                cid = await self.store.create_conversation(
                    user.uid, await self._make_title(user_text)
                )
            await self.store.append_exchange(user.uid, cid, user_text, content, steps=steps)

        if body.use_memory and not triggered:
            await self._remember(user, cid, user_text, content)

        return ChatResponse(content=content, conversation_id=cid,
                            guardrail_triggered=triggered, steps=steps)

    # ---- streaming turn ---------------------------------------------------

    async def stream(self, body: ChatRequest, user):
        """Resolve the turn, then hand back the SSE generator.

        Resolution happens *before* the response starts on purpose: once
        StreamingResponse has sent its headers, an HTTPException can only
        truncate the body, so a caller asking for a model above their tier
        would see an empty 200 instead of a 403. Awaiting here keeps that
        error a real status code.
        """
        prepared = await self._prepare(body, user)
        return self._stream_frames(body, user, *prepared)

    async def _stream_frames(self, body: ChatRequest, user, rails, raw_llm, messages, multimodal):
        """
        Yields SSE frames:
          meta  → the (possibly new) conversation id, sent first
          step  → an agent decision, as it happens
          token → guarded output chunks
          title → generated title, new conversations only
          done
        """
        user_text = messages[-1]["content"]

        def frame(payload: dict) -> str:
            return f"data: {json.dumps(payload)}\n\n"

        cid = body.conversation_id
        new_conversation = cid is None
        steps: list[dict] = []

        if self.store.enabled:
            await self.store.ensure_user(user.uid, user.email, user.tier)
            if new_conversation:
                # Placeholder title now, generated one after the exchange.
                cid = await self.store.create_conversation(
                    user.uid, user_text[:48] or "New chat"
                )
        yield frame({"type": "meta", "conversation_id": cid})

        if multimodal:
            # Guarded non-streaming call, chunked out for a live feel.
            content, triggered = await self._guarded_multimodal(rails, raw_llm, messages)
            for i in range(0, len(content), 24):
                yield frame({"type": "token", "text": content[i:i + 24]})
        elif getattr(rails, "needs_user", False):
            full = []
            async for item in rails.stream_async(messages, user_id=user.uid):
                if isinstance(item, dict) and item.get("kind") == "step":
                    steps.append(item["step"])
                    yield frame({"type": "step", "step": item["step"]})
                    continue
                text = item["text"] if isinstance(item, dict) else item
                full.append(text)
                yield frame({"type": "token", "text": text})
            content = "".join(full)
            triggered = REFUSAL_TEXT in content
        else:
            full = []
            async for chunk in rails.stream_async(messages=messages):
                full.append(chunk)
                yield frame({"type": "token", "text": chunk})
            content = "".join(full)
            triggered = REFUSAL_TEXT in content

        if self.store.enabled and cid:
            await self.store.append_exchange(user.uid, cid, user_text, content, steps=steps)
            if new_conversation:
                title = await self._make_title(user_text)
                await self.store.set_title(user.uid, cid, title)
                yield frame({"type": "title", "title": title})

        if body.use_memory and not triggered:
            await self._remember(user, cid, user_text, content)

        yield frame({"type": "done"})
