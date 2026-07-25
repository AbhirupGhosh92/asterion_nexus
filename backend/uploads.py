"""
Media uploads — images/audio/video in Firebase Storage (GCS).

All access is server-side with Admin credentials; objects live under
uploads/{uid}/... and every route scopes by the verified uid, so users can
only ever see their own files. Files can be attached to chat messages for
multimodal (Gemini) analysis.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response
from google.cloud import firestore, storage

from auth import AuthedUser, verify_firebase_token

log = logging.getLogger("ai-platform.uploads")

router = APIRouter(prefix="/api/uploads")

MAX_BYTES = 25 * 1024 * 1024  # 25 MB
ALLOWED_PREFIXES = ("image/", "audio/", "video/")


class MediaStore:
    def __init__(self, project: str, bucket: str):
        self._enabled = bool(project and bucket)
        if self._enabled:
            self._bucket = storage.Client(project=project).bucket(bucket)
            self._db = firestore.AsyncClient(project=project)
        else:
            log.warning("MediaStore disabled (no GCP_PROJECT/STORAGE_BUCKET)")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _doc(self, uid: str, file_id: str):
        return self._db.collection("users").document(uid).collection("uploads").document(file_id)

    async def save(self, uid: str, name: str, content_type: str, data: bytes) -> dict:
        file_id = uuid.uuid4().hex
        path = f"uploads/{uid}/{file_id}"
        blob = self._bucket.blob(path)
        await asyncio.to_thread(blob.upload_from_string, data, content_type=content_type)
        record = {
            "name": name,
            "content_type": content_type,
            "size": len(data),
            "path": path,
            "ts": datetime.now(timezone.utc),
        }
        await self._doc(uid, file_id).set(record)
        return {"id": file_id, "name": name, "content_type": content_type, "size": len(data)}

    async def get(self, uid: str, file_id: str) -> tuple[dict, bytes] | None:
        doc = await self._doc(uid, file_id).get()
        if not doc.exists:
            return None
        meta = doc.to_dict()
        blob = self._bucket.blob(meta["path"])
        data = await asyncio.to_thread(blob.download_as_bytes)
        return meta, data

    async def list(self, uid: str, limit: int = 100) -> list[dict]:
        query = (
            self._db.collection("users").document(uid).collection("uploads")
            .order_by("ts", direction=firestore.Query.DESCENDING).limit(limit)
        )
        return [
            {"id": d.id, "name": d.get("name"), "content_type": d.get("content_type"),
             "size": d.get("size")}
            async for d in query.stream()
        ]


def _store(request: Request) -> MediaStore:
    store: MediaStore = request.app.state.media
    if not store.enabled:
        raise HTTPException(503, "Media storage not configured")
    return store


@router.post("")
async def upload(
    file: UploadFile, request: Request, user: AuthedUser = Depends(verify_firebase_token)
):
    content_type = file.content_type or ""
    if not content_type.startswith(ALLOWED_PREFIXES):
        raise HTTPException(415, "Only image, audio, and video files are accepted")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"File exceeds {MAX_BYTES // (1024*1024)} MB limit")
    return await _store(request).save(user.uid, file.filename or "upload", content_type, data)


@router.get("")
async def list_uploads(request: Request, user: AuthedUser = Depends(verify_firebase_token)):
    return await _store(request).list(user.uid)


@router.get("/{file_id}/content")
async def get_content(
    file_id: str, request: Request, user: AuthedUser = Depends(verify_firebase_token)
):
    found = await _store(request).get(user.uid, file_id)
    if found is None:
        raise HTTPException(404, "File not found")
    meta, data = found
    return Response(content=data, media_type=meta["content_type"])
