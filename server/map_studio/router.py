"""HTTP boundary for the durable Map Studio editor and public manifest."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Path, Request, Response
from fastapi.responses import JSONResponse

from . import models
from . import store


router = APIRouter(prefix="/api/bff/map-studio", tags=["map-studio"])
public_router = APIRouter(prefix="/api/public/map-studio", tags=["public-map-studio"])
_MAP_KEY = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$")


def _map_key(value: str = Path(..., min_length=1, max_length=100)) -> str:
    if not _MAP_KEY.fullmatch(value):
        raise HTTPException(status_code=422, detail="map_studio_invalid")
    return value


async def actor(request: Request, *, write: bool = False):
    return await store.actor(request, write=write)


def _idempotency(value: str | None) -> str:
    if not value or len(value) > 128 or any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise HTTPException(status_code=400, detail="idempotency_key_required")
    return value


def _private(payload: Any) -> JSONResponse:
    return JSONResponse(payload, headers={"Cache-Control": "private, no-store", "Vary": "Cookie"})


@router.get("/projects")
async def projects(request: Request):
    record = await actor(request)
    return _private({"projects": await store.list_projects(record), "isAdmin": await store.is_admin(record)})


@router.get("/projects/{key}")
async def project(key: str, request: Request):
    record = await actor(request)
    return _private(await store.get_project(record, _map_key(key)))


@router.post("/projects/{key}/lease")
async def lease(key: str, body: models.LeaseRequest, request: Request):
    record = await actor(request, write=True)
    return _private(await store.acquire_lease(record, _map_key(key), body.clientId))


@router.post("/projects/{key}/lease/release")
async def release_lease(key: str, body: models.LeaseRequest, request: Request):
    record = await actor(request, write=True)
    return _private(await store.release_lease(record, _map_key(key), body.clientId))


@router.post("/projects/{key}/draft")
async def draft(key: str, body: models.DraftRequest, request: Request):
    record = await actor(request, write=True)
    return _private(await store.save_draft(record, _map_key(key), body.document.model_dump(mode="json", exclude_none=True), body.expectedRevision, body.clientId))


@router.get("/projects/{key}/versions")
async def version_list(key: str, request: Request):
    record = await actor(request)
    return _private(await store.versions(record, _map_key(key)))


@router.post("/projects/{key}/publish")
async def publish(
    key: str,
    body: models.PublishRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    record = await actor(request, write=True)
    map_key = _map_key(key)
    key_value = _idempotency(idempotency_key)
    # Asset preparation is intentionally outside the pointer transaction.  The
    # RPC still validates the lease and expected revision atomically before it
    # can make the new version public.
    current = await store.get_project(record, map_key)
    if (current.get("draft") or {}).get("revision") != body.expectedRevision:
        raise HTTPException(status_code=409, detail="map_studio_conflict")
    document = (current.get("draft") or {}).get("document")
    if not isinstance(document, dict):
        raise HTTPException(status_code=409, detail="map_studio_draft_missing")
    from .assets import prepare_public_assets  # parent-owned storage boundary

    prepared = await prepare_public_assets(record, map_key, document)
    if isinstance(prepared, dict):
        prepared = prepared.get("assets", [])
    public_assets = []
    for item in prepared or []:
        if isinstance(item, models.Asset):
            public_assets.append(item.model_dump(mode="json"))
        elif isinstance(item, dict):
            public_assets.append(item)
    return _private(await store.publish(record, map_key, body.expectedRevision, body.clientId, key_value, public_assets))


@router.post("/projects/{key}/rollback")
async def rollback(
    key: str,
    body: models.RollbackRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    record = await actor(request, write=True)
    return _private(await store.rollback(record, _map_key(key), str(body.versionId), body.clientId, _idempotency(idempotency_key)))


@router.post("/projects/{key}/members")
async def members(key: str, body: models.MemberRequest, request: Request):
    record = await actor(request, write=True)
    result = await store.rpc(record, "map_studio_set_member", {
        "p_map_key": _map_key(key), "p_user_id": str(body.userId), "p_enabled": body.enabled,
    })
    return _private({"ok": result is None or result is True or result == {} or (isinstance(result, dict) and result.get("ok") is True)})


@router.post("/projects/{key}/disable")
async def disable(key: str, request: Request):
    record = await actor(request, write=True)
    await store.rpc(record, "map_studio_disable_project", {"p_map_key": _map_key(key)})
    return _private({"ok": True})


@public_router.get("/{key}")
async def public_project(key: str):
    return JSONResponse(
        await store.public_manifest(_map_key(key)),
        headers={"Cache-Control": "public, max-age=60", "X-Content-Type-Options": "nosniff"},
    )


__all__ = ["router", "public_router", "actor"]
