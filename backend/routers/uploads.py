"""Upload endpoints — thin HTTP layer over repositories/media_repo."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response

from core.auth import AuthedUser, verify_firebase_token
from repositories.media_repo import ALLOWED_PREFIXES, MAX_BYTES, MediaStore

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


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
