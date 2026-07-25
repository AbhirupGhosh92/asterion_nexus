"""
Firestore persistence — user profiles and per-user chat history.

Layout (all access is server-side via Admin credentials; clients never talk
to Firestore directly, so the verified-uid scoping here IS the access rule):

  users/{uid}                          profile: email, tier, timestamps
  users/{uid}/conversations/{cid}      title, created_at, updated_at, message_count
  users/{uid}/conversations/{cid}/messages/{mid}   role, content, seq, ts
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from google.cloud import firestore

log = logging.getLogger("ai-platform.store")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ChatStore:
    def __init__(self, project: str):
        self._db = firestore.AsyncClient(project=project) if project else None
        if not self._db:
            log.warning("ChatStore disabled (no GCP_PROJECT) — history not persisted")

    @property
    def enabled(self) -> bool:
        return self._db is not None

    def _user(self, uid: str):
        return self._db.collection("users").document(uid)

    async def ensure_user(self, uid: str, email: str | None, tier: str) -> None:
        if not self._db:
            return
        await self._user(uid).set(
            {"email": email, "tier": tier, "last_seen": _now()}, merge=True
        )

    # ---- conversations -----------------------------------------------------

    async def list_conversations(self, uid: str, limit: int = 50) -> list[dict]:
        if not self._db:
            return []
        query = (
            self._user(uid)
            .collection("conversations")
            .order_by("updated_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        out = []
        async for doc in query.stream():
            data = doc.to_dict()
            out.append(
                {
                    "id": doc.id,
                    "title": data.get("title", "Untitled"),
                    "updated_at": data.get("updated_at").isoformat() if data.get("updated_at") else None,
                    "message_count": data.get("message_count", 0),
                }
            )
        return out

    async def create_conversation(self, uid: str, title: str) -> str:
        ref = self._user(uid).collection("conversations").document()
        await ref.set(
            {"title": title, "created_at": _now(), "updated_at": _now(), "message_count": 0}
        )
        return ref.id

    async def get_messages(self, uid: str, cid: str) -> list[dict] | None:
        """Returns None if the conversation doesn't exist (or isn't this user's)."""
        if not self._db:
            return []
        conv = await self._user(uid).collection("conversations").document(cid).get()
        if not conv.exists:
            return None
        query = (
            self._user(uid)
            .collection("conversations")
            .document(cid)
            .collection("messages")
            .order_by("seq")
        )
        return [
            {"role": d.get("role"), "content": d.get("content")}
            async for d in query.stream()
        ]

    async def append_exchange(
        self, uid: str, cid: str, user_content: str, assistant_content: str
    ) -> None:
        if not self._db:
            return
        conv_ref = self._user(uid).collection("conversations").document(cid)
        conv = await conv_ref.get()
        seq = (conv.to_dict() or {}).get("message_count", 0)
        batch = self._db.batch()
        msgs = conv_ref.collection("messages")
        batch.set(msgs.document(), {"role": "user", "content": user_content, "seq": seq, "ts": _now()})
        batch.set(msgs.document(), {"role": "assistant", "content": assistant_content, "seq": seq + 1, "ts": _now()})
        batch.update(conv_ref, {"updated_at": _now(), "message_count": seq + 2})
        await batch.commit()

    async def set_title(self, uid: str, cid: str, title: str) -> None:
        if not self._db:
            return
        await self._user(uid).collection("conversations").document(cid).update({"title": title})

    async def delete_conversation(self, uid: str, cid: str) -> None:
        if not self._db:
            return
        conv_ref = self._user(uid).collection("conversations").document(cid)
        async for msg in conv_ref.collection("messages").stream():
            await msg.reference.delete()
        await conv_ref.delete()
