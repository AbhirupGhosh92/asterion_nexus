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
import time
from datetime import datetime, timezone

log = logging.getLogger("ai-platform.imagegen")

REFUSAL_TEXT = "I can't help with that"
# Vertex's image model allows only a few requests per minute; generation
# already takes ~10s, so waiting a bit longer beats a spurious failure.
RATE_LIMIT_RETRIES = 4
RETRY_BASE_DELAY = 5.0  # seconds; doubles each attempt (5 + 10 + 20)
# How much prior conversation to give the model so follow-ups like
# "make it blue instead" know what "it" refers to.
CONTEXT_TURNS = 6


class RateLimited(RuntimeError):
    """Vertex returned 429 for every attempt."""


def _text(content) -> str:
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if p.get("type") == "text")
    return content


def _as_contents(messages: list[dict]) -> list[dict]:
    """
    Recent turns in google-genai `contents` form, so the model can resolve
    follow-ups ("make it blue instead"). Stored image tokens are dropped —
    they're internal ids, meaningless to the model.
    """
    import re

    turns = [m for m in messages if m.get("role") in ("user", "assistant")]
    contents = []
    for m in turns[-CONTEXT_TURNS:]:
        text = re.sub(r"\[image:[a-f0-9]{32}\]", "", _text(m["content"])).strip()
        if not text:
            continue
        contents.append({
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": text}],
        })
    return contents or [{"role": "user", "parts": [{"text": _text(messages[-1]["content"])}]}]


class ImageGenRails:
    needs_user = True  # generate_async/stream_async take user_id

    def __init__(self, *, project: str, region: str, model: str, screen_rails, media_store):
        self._project = project
        self._region = region
        self._model_name = model
        self._screen = screen_rails
        self._media = media_store
        self._model = None

    def _generate_bytes(self, contents) -> tuple[bytes | None, str, str]:
        """
        Returns (image_bytes | None, mime_type, text).

        A text-only reply is NOT an error — the model is conversational and
        sometimes answers or asks a question instead of drawing. Callers show
        that text. Rate limits are retried with backoff, because Vertex's
        image model has a low requests-per-minute ceiling and a burst of
        generations otherwise fails for no good reason.
        """
        from google import genai
        from google.genai import types
        from google.genai import errors as genai_errors

        if self._model is None:
            self._model = genai.Client(
                vertexai=True, project=self._project, location=self._region
            )

        last_error: Exception | None = None
        for attempt in range(RATE_LIMIT_RETRIES):
            try:
                resp = self._model.models.generate_content(
                    model=self._model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_modalities=["TEXT", "IMAGE"]
                    ),
                )
                break
            except genai_errors.ClientError as exc:
                if getattr(exc, "code", None) != 429:
                    raise
                last_error = exc
                if attempt == RATE_LIMIT_RETRIES - 1:
                    raise RateLimited() from exc
                delay = RETRY_BASE_DELAY * (2**attempt)
                log.warning("image model rate-limited; retrying in %.0fs", delay)
                time.sleep(delay)
        else:  # pragma: no cover - loop always breaks or raises
            raise RateLimited() from last_error

        image, mime, text_parts = None, "image/png", []
        for cand in resp.candidates or []:
            for part in (cand.content.parts if cand.content else []) or []:
                if part.inline_data and image is None:
                    image = part.inline_data.data
                    mime = part.inline_data.mime_type or mime
                elif part.text:
                    text_parts.append(part.text)
        return image, mime, " ".join(text_parts).strip()

    async def generate_async(self, messages: list[dict], *, user_id: str = "anonymous") -> dict:
        text_msgs = [{"role": m["role"], "content": _text(m["content"])} for m in messages]

        checked = await self._screen.generate_async(
            messages=text_msgs, options={"rails": ["input"]}
        )
        inp = checked.response[0]["content"]
        if REFUSAL_TEXT in inp:
            return {"role": "assistant", "content": inp}

        try:
            data, mime, text = await asyncio.to_thread(
                self._generate_bytes, _as_contents(messages)
            )
        except RateLimited:
            return {
                "role": "assistant",
                "content": "⚠ The image model is rate-limited right now (Vertex AI "
                           "allows only a few image requests per minute). Wait a "
                           "moment and try again.",
            }
        except Exception as exc:
            log.warning("Image generation failed: %s", exc)
            return {
                "role": "assistant",
                "content": f"⚠ Image generation failed: {str(exc)[:200]}",
            }

        # Text-only reply: the model answered or asked something instead of
        # drawing. Show what it said rather than pretending it broke.
        if data is None:
            return {
                "role": "assistant",
                "content": text or "⚠ The model returned neither an image nor a "
                                   "message — try rephrasing the prompt.",
            }

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        ext = "jpg" if "jpeg" in mime else "png"
        saved = await self._media.save(
            user_id, f"generated-{stamp}.{ext}", mime, data
        )
        content = f"[image:{saved['id']}]"
        if text:
            content += f"\n{text}"
        return {"role": "assistant", "content": content}

    async def stream_async(self, messages: list[dict], *, user_id: str = "anonymous"):
        result = await self.generate_async(messages, user_id=user_id)
        yield result["content"]
