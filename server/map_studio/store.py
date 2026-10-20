"""PostgREST RPC adapter for Map Studio.

There is deliberately no local cache or in-memory fallback here.  The lease,
revision compare-and-swap, publication pointer, and idempotency records are
all owned by Postgres transactions.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import HTTPException
from fastapi import Request

from .storage import supabase_request
from .config import settings


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value


def _provider_message(response: Any) -> str:
    try:
        body = response.json()
    except Exception:
        return ""
    if isinstance(body, dict):
        return str(body.get("message") or body.get("hint") or body.get("details") or "")
    return str(body or "")


def _error(response: Any) -> HTTPException:
    message = _provider_message(response).lower()
    if any(token in message for token in ("revision_conflict", "expected_revision", "idempotency_conflict", "lease_conflict", "lease_required", "version_not_found", "asset_referenced", "asset_not_ready")):
        status = 409
    elif any(token in message for token in ("not_found", "project_not_found", "asset_not_found")):
        status = 404
    elif response.status_code in (401, 403) or any(token in message for token in ("denied", "forbidden", "membership", "admin_required", "owner_required", "disabled")):
        status = 403
    elif response.status_code in (400, 422):
        status = 422
    else:
        status = 503
    # Provider details can contain SQL and identifiers.  Keep the browser error
    # stable and intentionally omit the upstream message.
    detail = "map_studio_conflict" if status == 409 else (
        "map_studio_not_found" if status == 404 else
        "map_studio_forbidden" if status == 403 else
        "map_studio_invalid" if status == 422 else "map_studio_unavailable"
    )
    return HTTPException(status_code=status, detail=detail)


async def rpc(record: Any, name: str, arguments: dict[str, Any]) -> Any:
    """Call a user-scoped RPC using only the resolved browser session JWT."""
    actor_id = record.get("id") if isinstance(record, dict) else getattr(record, "id", None)
    if not actor_id:
        raise HTTPException(status_code=401, detail="authentication_required")
    response = await supabase_request(
        "POST", f"/rest/v1/rpc/{name}", json_body={**arguments, "p_actor": str(actor_id)}
    )
    if not response.is_success:
        raise _error(response)
    try:
        value = response.json()
        # Composite-returning functions use PostgREST's row-array representation.
        if name in {"map_studio_asset_get", "map_studio_asset_register"} and isinstance(value, list):
            return value[0] if value else None
        return value
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="map_studio_unavailable") from exc


async def actor(request: Request, *, write: bool = False) -> Any:
    """Resolve the standalone verified session; auth owns CSRF enforcement."""
    from .auth import actor as resolve_actor

    return await resolve_actor(request, write=write)


async def require_member(record: Any, map_key: str) -> dict[str, Any]:
    """Make membership an explicit user-JWT RPC check for storage callers."""
    return await get_project(record, map_key)


async def public_rpc(name: str, arguments: dict[str, Any]) -> Any:
    response = await supabase_request("POST", f"/rest/v1/rpc/{name}", json_body=arguments)
    if not response.is_success:
        raise _error(response)
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="map_studio_unavailable") from exc


def _project(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "mapKey": row.get("map_key", row.get("mapKey")),
        "title": row.get("title"),
        "city": row.get("city"),
        "publicPath": row.get("public_path", row.get("publicPath")),
        "center": row.get("center"),
        "sourceRevision": row.get("source_revision", row.get("sourceRevision")),
    }


def _business(row: dict[str, Any]) -> dict[str, Any]:
    result = {"id": row.get("id"), "name": row.get("name")}
    if row.get("category"):
        result["category"] = row["category"]
    if isinstance(row.get("location"), dict):
        result["location"] = {key: row["location"][key] for key in
                              ("lat", "lng", "precisionNote") if row["location"].get(key) is not None}
    if row.get("logo_url", row.get("logoUrl")):
        result["logoUrl"] = row.get("logo_url", row.get("logoUrl"))
    return result


def public_asset_url(path: str) -> str:
    base = settings.supabase_url.rstrip("/")
    return f"{base}/storage/v1/object/public/map-studio-published/{quote(path.lstrip('/'), safe='/')}"


def _asset(row: dict[str, Any], *, public: bool = False) -> dict[str, Any]:
    path = row.get("public_path") or row.get("publicPath") or row.get("processed_path") or row.get("processedPath") or row.get("url")
    url = row.get("url") or (public_asset_url(str(path)) if public and path else "")
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "altText": row.get("alt_text", row.get("altText")),
        "rights": row.get("rights"),
        "url": url,
        "width": row.get("width"),
        "height": row.get("height"),
        "state": row.get("state"),
    }


async def is_admin(record: Any) -> bool:
    result = await rpc(record, "map_studio_owner_check", {})
    return _first(result) is True or (isinstance(result, dict) and result.get("isOwner") is True)


async def list_projects(record: Any) -> list[dict[str, Any]]:
    rows = await rpc(record, "map_studio_list_projects", {})
    if isinstance(rows, dict):
        rows = rows.get("projects", [])
    return [_project(row) for row in rows or [] if isinstance(row, dict)]


async def get_project(record: Any, map_key: str) -> dict[str, Any]:
    row = _first(await rpc(record, "map_studio_get_project", {"p_map_key": map_key}))
    if not isinstance(row, dict):
        raise HTTPException(status_code=404, detail="map_studio_not_found")
    return {
        "project": _project(row.get("project", row)),
        "businesses": [_business(item) for item in row.get("businesses", []) if isinstance(item, dict)],
        "draft": row.get("draft") or {"document": None, "revision": 0},
        "canEdit": bool(row.get("can_edit", row.get("canEdit", True))),
    }


async def acquire_lease(record: Any, map_key: str, client_id: str) -> dict[str, Any]:
    result = _first(await rpc(record, "map_studio_acquire_lease", {"p_map_key": map_key, "p_client_id": client_id}))
    return result if isinstance(result, dict) else {"clientId": client_id, "expiresAt": result}


async def release_lease(record: Any, map_key: str, client_id: str) -> dict[str, Any]:
    result = _first(await rpc(record, "map_studio_release_lease", {"p_map_key": map_key, "p_client_id": client_id}))
    return result if isinstance(result, dict) else {"ok": bool(result is True or result is None)}


async def save_draft(record: Any, map_key: str, document: dict[str, Any], expected_revision: int, client_id: str) -> dict[str, Any]:
    result = _first(await rpc(record, "map_studio_save_draft", {
        "p_map_key": map_key, "p_document": document, "p_expected_revision": expected_revision, "p_client_id": client_id,
    }))
    if not isinstance(result, dict):
        raise HTTPException(status_code=503, detail="map_studio_unavailable")
    return {"revision": result.get("revision"), "document": result.get("document")}


async def versions(record: Any, map_key: str) -> dict[str, Any]:
    result = _first(await rpc(record, "map_studio_list_versions", {"p_map_key": map_key}))
    if not isinstance(result, dict):
        return {"versions": [], "publishedVersionId": None}
    items = result.get("versions") or []
    return {
        "versions": [{
            "id": item.get("id"), "createdAt": item.get("created_at", item.get("createdAt")),
            "createdBy": item.get("created_by", item.get("createdBy")), "revision": item.get("revision"),
        } for item in items if isinstance(item, dict)],
        "publishedVersionId": result.get("published_version_id", result.get("publishedVersionId")),
    }


async def publish(record: Any, map_key: str, expected_revision: int, client_id: str, idempotency_key: str, public_assets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    result = _first(await rpc(record, "map_studio_publish", {
        "p_map_key": map_key, "p_expected_revision": expected_revision, "p_client_id": client_id,
        "p_idempotency_key": idempotency_key, "p_assets": public_assets or [],
    }))
    if not isinstance(result, dict) or not result.get("version_id", result.get("versionId")):
        raise HTTPException(status_code=503, detail="map_studio_unavailable")
    return {"versionId": result.get("version_id", result.get("versionId"))}


async def rollback(record: Any, map_key: str, version_id: str, client_id: str, idempotency_key: str) -> dict[str, Any]:
    result = _first(await rpc(record, "map_studio_rollback", {
        "p_map_key": map_key, "p_version_id": version_id, "p_client_id": client_id,
        "p_idempotency_key": idempotency_key,
    }))
    if not isinstance(result, dict) or not result.get("version_id", result.get("versionId")):
        raise HTTPException(status_code=503, detail="map_studio_unavailable")
    return {"versionId": result.get("version_id", result.get("versionId"))}


async def list_assets(record: Any, map_key: str) -> list[dict[str, Any]]:
    rows = await rpc(record, "map_studio_asset_list", {"p_map_key": map_key})
    if isinstance(rows, dict):
        rows = rows.get("assets", [])
    return [_asset(row) for row in rows or [] if isinstance(row, dict) and row.get("state") == "ready"]


async def public_manifest(map_key: str) -> dict[str, Any]:
    if not settings.public_manifests_enabled:
        raise HTTPException(status_code=404, detail="map_studio_not_found")
    result = _first(await public_rpc("map_studio_public_manifest", {"p_map_key": map_key}))
    if not isinstance(result, dict) or not result.get("version_id"):
        raise HTTPException(status_code=404, detail="map_studio_not_found")
    return {
        "versionId": result.get("version_id"),
        "document": result.get("document"),
        "assets": [_asset(item, public=True) for item in result.get("assets", []) if isinstance(item, dict) and item.get("state") == "ready"],
    }
