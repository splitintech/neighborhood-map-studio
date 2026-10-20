"""Bounded server-only Supabase transport; no credentials are returned to browsers."""
import httpx
from fastapi import HTTPException
from .config import settings


def supabase_headers() -> dict[str, str]:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise HTTPException(503, "durable_storage_not_configured")
    return {"apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
            "Content-Type": "application/json", "Accept": "application/json"}


async def supabase_request(method: str, path: str, *, json_body=None, params=None,
                           extra_headers=None, **_kwargs) -> httpx.Response:
    if not path.startswith("/rest/v1/") or "?" in path or ".." in path:
        raise ValueError("unregistered_storage_path")
    headers = supabase_headers()
    headers.update(extra_headers or {})
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=3), follow_redirects=False) as client:
            return await client.request(method, settings.supabase_url + path,
                                        headers=headers, params=params, json=json_body)
    except httpx.HTTPError:
        raise HTTPException(503, "durable_storage_unavailable")
