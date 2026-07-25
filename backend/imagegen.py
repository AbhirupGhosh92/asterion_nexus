"""
Image generation as a chat model — Vertex AI Imagen.

Registry entries with provider "vertexai_image" resolve to ImageGenRails:
the user's prompt passes the NeMo INPUT rails, Imagen generates, the PNG is
stored in Firebase Storage under the requesting user (same scoping as
uploads), and the assistant message carries an `[image:<file_id>]` token the
UI resolves through the authenticated /api/uploads/{id}/content route.
Imagen's own safety filters remain active on the output side.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

log = logging.getLogger("ai-platform.imagegen")

REFUSAL_TEXT = "I can't help with that"


def _text(content) -> str:
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if p.get("type") == "text")
    return content


class ImageGenRails:
    needs_user = True  # generate_async/stream_async take user_id

    def __init__(self, *, project: str, region: str, model: str, screen_rails, media_store):
        self._project = project
        self._region = region
        self._model_name = model
        self._screen = screen_rails
        self._media = media_store
        self._model = None

    def _generate_bytes(self, prompt: str) -> tuple[bytes, str, str]:
        """Returns (image_bytes, mime_type, caption). Uses a Gemini image
        model via google-genai (classic Imagen publisher models were removed
        from Vertex in June 2026)."""
        from google import genai
        from google.genai import types

        if self._model is None:
            self._model = genai.Client(
                vertexai=True, project=self._project, location=self._region
            )
        resp = self._model.models.generate_content(
            model=self._model_name,
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )
        image = None
        mime = "image/png"
        caption_parts: list[str] = []
        for cand in resp.candidates or []:
            for part in (cand.content.parts if cand.content else []) or []:
                if part.inline_data and image is None:
                    image = part.inline_data.data
                    mime = part.inline_data.mime_type or mime
                elif part.text:
                    caption_parts.append(part.text)
        if image is None:
            raise RuntimeError("Model returned no image (safety filter or refusal)")
        return image, mime, " ".join(caption_parts).strip()

    async def generate_async(self, messages: list[dict], *, user_id: str = "anonymous") -> dict:
        text_msgs = [{"role": m["role"], "content": _text(m["content"])} for m in messages]

        checked = await self._screen.generate_async(
            messages=text_msgs, options={"rails": ["input"]}
        )
        inp = checked.response[0]["content"]
        if REFUSAL_TEXT in inp:
            return {"role": "assistant", "content": inp}

        prompt = _text(messages[-1]["content"])
        try:
            data, mime, caption = await asyncio.to_thread(self._generate_bytes, prompt)
        except Exception as exc:
            log.warning("Image generation failed: %s", exc)
            return {
                "role": "assistant",
                "content": "⚠ Image generation failed — the prompt may have been "
                           "filtered, or the model is unavailable. Try rephrasing.",
            }

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        ext = "jpg" if "jpeg" in mime else "png"
        saved = await self._media.save(
            user_id, f"generated-{stamp}.{ext}", mime, data
        )
        content = f"[image:{saved['id']}]"
        if caption:
            content += f"\n{caption}"
        return {"role": "assistant", "content": content}

    async def stream_async(self, messages: list[dict], *, user_id: str = "anonymous"):
        result = await self.generate_async(messages, user_id=user_id)
        yield result["content"]
