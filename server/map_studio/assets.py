"""Member-authorized private uploads and immutable published artwork."""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from .config import settings
from .storage import supabase_headers
from .store import actor, rpc

router = APIRouter(prefix="/api/bff/map-studio", tags=["map-studio-assets"])
PRIVATE_BUCKET = "map-studio-private"
PUBLIC_BUCKET = "map-studio-published"
MAX_INPUT = 5 * 1024 * 1024
MAX_BODY = 7 * 1024 * 1024 + 8192
_workers = asyncio.Semaphore(1)


class Upload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    altText: str = Field(min_length=1, max_length=500)
    rights: str = Field(min_length=1, max_length=1000)
    mimeType: str
    dataBase64: str = Field(max_length=7 * 1024 * 1024)


async def member(record, map_key: str):
    # Service-role RPC explicitly checks the verified actor's assignment.
    return await rpc(record, "map_studio_get_project", {"p_map_key": map_key})


def asset_view(row: dict, *, public: bool = False) -> dict:
    asset_id = str(row["id"])
    if public:
        url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/public/{PUBLIC_BUCKET}/{row['sha256']}.webp"
    else:
        url = f"/api/bff/map-studio/projects/{quote(row['map_key'], safe='')}/assets/{asset_id}/content"
    return {"id": asset_id, "name": row["name"], "altText": row["alt_text"],
            "rights": row["rights"], "width": row["width"], "height": row["height"],
            "state": row["state"], "url": url}


async def storage(method: str, bucket: str, path: str, content: bytes | None = None,
                  mime: str = "application/octet-stream") -> httpx.Response:
    headers = supabase_headers()
    headers.update({"Content-Type": mime, "x-upsert": "false"})
    if method == "POST":
        headers["Cache-Control"] = "max-age=31536000, immutable" if bucket == PUBLIC_BUCKET else "private, max-age=0"
    url = f"{settings.supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{quote(path, safe='/')}"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.request(method, url, headers=headers, content=content)
    except httpx.HTTPError:
        raise HTTPException(503, "asset_storage_unavailable")
    if method == "GET" and len(response.content) > 16 * 1024 * 1024:
        raise HTTPException(503, "asset_storage_response_invalid")
    return response


async def decode_image(body: Upload) -> tuple[bytes, bytes, int, int]:
    try:
        original = base64.b64decode(body.dataBase64, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, "image_encoding_invalid")
    if not original or len(original) > MAX_INPUT:
        raise HTTPException(413, "image_exceeds_5mb")
    env = {"PATH": os.defpath, "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
           "PYTHONDONTWRITEBYTECODE": "1"}
    if sys.platform == "darwin":
        # Native Homebrew Cairo for local development; no parent credentials.
        env["DYLD_FALLBACK_LIBRARY_PATH"] = "/opt/homebrew/lib:/usr/local/lib:/usr/lib"
    async with _workers:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "server.map_studio.image_worker",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=env)
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(
                json.dumps({"dataBase64": body.dataBase64, "mimeType": body.mimeType}).encode()), 12)
        except (TimeoutError, asyncio.CancelledError):
            process.kill()
            await process.wait()
            raise HTTPException(422, "image_processing_timeout")
    if process.returncode != 0:
        raise HTTPException(422, "image_rejected")
    result = json.loads(stdout)
    return original, base64.b64decode(result["dataBase64"], validate=True), result["width"], result["height"]


@router.get("/projects/{map_key}/assets")
async def list_assets(map_key: str, request: Request):
    record = await actor(request)
    rows = await rpc(record, "map_studio_asset_list", {"p_map_key": map_key})
    return {"assets": [asset_view(row) for row in rows]}


@router.post("/projects/{map_key}/assets")
async def upload_asset(map_key: str, request: Request):
    record = await actor(request, write=True)
    await member(record, map_key)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BODY:
            raise HTTPException(413, "image_exceeds_5mb")
        raw.extend(chunk)
    try:
        body = Upload.model_validate_json(raw)
    except ValueError:
        raise HTTPException(422, "asset_metadata_invalid")
    original, processed, width, height = await decode_image(body)
    asset_id = str(uuid4())
    digest = hashlib.sha256(processed).hexdigest()
    prefix = f"{map_key}/{asset_id}"
    original_path, processed_path = f"{prefix}/original", f"{prefix}/{digest}.webp"
    for path, content, mime in [(original_path, original, body.mimeType),
                                (processed_path, processed, "image/webp")]:
        response = await storage("POST", PRIVATE_BUCKET, path, content, mime)
        if not response.is_success:
            raise HTTPException(503, "asset_storage_unavailable")
    row = await rpc(record, "map_studio_asset_register", {"p_map_key": map_key, "p_asset": {
        "id": asset_id, "name": body.name.strip(), "alt_text": body.altText.strip(),
        "rights": body.rights.strip(), "mime_type": body.mimeType, "sha256": digest,
        "original_path": original_path, "processed_path": processed_path,
        "width": width, "height": height, "byte_size": len(original), "state": "ready"}})
    return {"asset": asset_view(row)}


@router.get("/projects/{map_key}/assets/{asset_id}/content")
async def asset_content(map_key: str, asset_id: UUID, request: Request):
    record = await actor(request)
    row = await rpc(record, "map_studio_asset_get", {"p_map_key": map_key, "p_asset_id": str(asset_id)})
    if not row or not row.get("id"):
        raise HTTPException(404, "asset_not_found")
    response = await storage("GET", PRIVATE_BUCKET, row["processed_path"])
    if not response.is_success:
        raise HTTPException(503, "asset_storage_unavailable")
    if hashlib.sha256(response.content).hexdigest() != row["sha256"]:
        raise HTTPException(503, "asset_integrity_failed")
    return Response(response.content, media_type="image/webp", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/projects/{map_key}/assets/{asset_id}/delete")
async def delete_asset(map_key: str, asset_id: UUID, request: Request):
    record = await actor(request, write=True)
    # RPC atomically checks references. Retained original bytes are cleaned by an
    # administrator later; a retry must never delete a newly referenced object.
    await rpc(record, "map_studio_asset_delete", {"p_map_key": map_key, "p_asset_id": str(asset_id)})
    return {"ok": True}


async def prepare_public_assets(record, map_key: str, document: dict) -> list[dict]:
    await member(record, map_key)
    ids = sorted({layer["assetId"] for layer in document["layers"] if layer.get("assetId")})
    assets = []
    for asset_id in ids:
        row = await rpc(record, "map_studio_asset_get", {"p_map_key": map_key, "p_asset_id": asset_id})
        if not row or not row.get("id"):
            raise HTTPException(404, "asset_not_found")
        if row["state"] != "ready":
            raise HTTPException(409, "asset_not_ready")
        source = await storage("GET", PRIVATE_BUCKET, row["processed_path"])
        if not source.is_success or hashlib.sha256(source.content).hexdigest() != row["sha256"]:
            raise HTTPException(503, "asset_integrity_failed")
        target = f"{row['sha256']}.webp"
        # Existing content-addressed objects are reused only after readback.
        await storage("POST", PUBLIC_BUCKET, target, source.content, "image/webp")
        verified = await storage("GET", PUBLIC_BUCKET, target)
        if not verified.is_success or hashlib.sha256(verified.content).hexdigest() != row["sha256"]:
            raise HTTPException(503, "published_asset_verification_failed")
        assets.append(asset_view(row, public=True))
    return assets
