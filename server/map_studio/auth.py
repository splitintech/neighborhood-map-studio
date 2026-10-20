"""GitHub OAuth with PKCE, owner-email verification, opaque revocable sessions."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .config import settings, OWNER_EMAIL, OWNER_ID
from .storage import supabase_request

router = APIRouter(prefix="/api/auth", tags=["authentication"])
COOKIE = "__Host-map-studio-session"
STATE_COOKIE = "__Host-map-studio-oauth"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def cookie_name(name: str) -> str:
    return name if settings.origin.startswith("https:") else name.removeprefix("__Host-")


def set_cookie(response, name: str, value: str, max_age: int):
    response.set_cookie(cookie_name(name), value, max_age=max_age, httponly=True,
                        secure=settings.origin.startswith("https:"), samesite="lax", path="/")


async def auth_rpc(name: str, args: dict):
    response = await supabase_request("POST", f"/rest/v1/rpc/{name}", json_body=args)
    if not response.is_success:
        raise HTTPException(503, "authentication_store_unavailable")
    return response.json()


def sign_state(payload: dict) -> str:
    if len(settings.session_secret) < 32:
        raise HTTPException(503, "authentication_not_configured")
    data = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = hmac.new(settings.session_secret.encode(), data.encode(), hashlib.sha256).hexdigest()
    return data + "." + signature


def read_state(value: str) -> dict:
    try:
        data, signature = value.split(".")
        expected = hmac.new(settings.session_secret.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        payload = json.loads(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)))
        if not 0 <= time.time() - payload["created"] <= 600:
            raise ValueError()
        return payload
    except Exception:
        raise HTTPException(400, "oauth_state_invalid")


def owner_verified(emails: list[dict]) -> bool:
    return any(item.get("verified") is True and
               str(item.get("email", "")).strip().lower() == OWNER_EMAIL for item in emails)


async def actor(request: Request, *, write: bool = False) -> dict:
    token = request.cookies.get(cookie_name(COOKIE), "")
    if len(token) < 32 or len(token) > 200:
        raise HTTPException(401, "authentication_required")
    session = await auth_rpc("map_studio_session_get", {"p_hash": digest(token)})
    if not session or session.get("email") != OWNER_EMAIL or session.get("id") != OWNER_ID:
        raise HTTPException(401, "authentication_required")
    origin = request.headers.get("origin")
    if origin and origin != settings.origin:
        raise HTTPException(403, "origin_not_allowed")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "cross_site_request_denied")
    if write:
        csrf = request.headers.get("x-csrf-token", "")
        if origin != settings.origin or not csrf or not hmac.compare_digest(csrf, session["csrfToken"]):
            raise HTTPException(403, "csrf_required")
    session["user"] = {"id": OWNER_ID, "email": OWNER_EMAIL}
    return session


@router.get("/session")
async def session(request: Request):
    record = await actor(request)
    return {"authenticated": True, "user": record["user"], "csrfToken": record["csrfToken"],
            "expiresAt": record["expiresAt"]}


@router.get("/login")
async def login():
    if settings.missing():
        raise HTTPException(503, "authentication_not_configured")
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    await auth_rpc("map_studio_login_state_create", {"p_hash": digest(state)})
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    query = urlencode({"client_id": settings.github_client_id,
                       "redirect_uri": settings.origin + "/api/auth/callback",
                       "scope": "read:user user:email", "state": state,
                       "code_challenge": challenge, "code_challenge_method": "S256",
                       "allow_signup": "false"})
    response = RedirectResponse("https://github.com/login/oauth/authorize?" + query, status_code=303)
    set_cookie(response, STATE_COOKIE, sign_state({"state": state, "verifier": verifier,
                                                 "created": time.time()}), 600)
    return response


@router.get("/callback")
async def callback(request: Request, code: str = "", state: str = ""):
    flow = read_state(request.cookies.get(cookie_name(STATE_COOKIE), ""))
    if not code or len(code) > 1024 or not state or not hmac.compare_digest(state, flow["state"]):
        raise HTTPException(400, "oauth_state_invalid")
    consumed = await auth_rpc("map_studio_login_state_consume", {"p_hash": digest(state)})
    if consumed is not True:
        raise HTTPException(400, "oauth_state_expired_or_reused")
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            token_response = await client.post("https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"}, data={
                    "client_id": settings.github_client_id, "client_secret": settings.github_client_secret,
                    "code": code, "redirect_uri": settings.origin + "/api/auth/callback",
                    "code_verifier": flow["verifier"]})
            token_response.raise_for_status()
            token = token_response.json().get("access_token")
            if not isinstance(token, str) or not token:
                raise HTTPException(401, "github_authentication_failed")
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                       "X-GitHub-Api-Version": "2022-11-28"}
            user_response = await client.get("https://api.github.com/user", headers=headers)
            email_response = await client.get("https://api.github.com/user/emails", headers=headers)
            user_response.raise_for_status()
            email_response.raise_for_status()
            user = user_response.json()
            emails = email_response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "github_authentication_unavailable")
    if not isinstance(emails, list) or not owner_verified(emails) or not user.get("id"):
        raise HTTPException(403, "owner_account_required")
    # Provider access tokens are neither persisted nor returned to the browser.
    session_token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    await auth_rpc("map_studio_session_create", {"p_hash": digest(session_token),
                   "p_actor": OWNER_ID, "p_email": OWNER_EMAIL, "p_github_id": str(user["id"]),
                   "p_csrf": csrf, "p_hours": min(8, max(1, settings.session_hours))})
    response = RedirectResponse("/map-studio/", status_code=303)
    response.delete_cookie(cookie_name(STATE_COOKIE), path="/")
    set_cookie(response, COOKIE, session_token, min(8, max(1, settings.session_hours)) * 3600)
    return response


@router.post("/logout")
async def logout(request: Request):
    await actor(request, write=True)
    token = request.cookies[cookie_name(COOKIE)]
    await auth_rpc("map_studio_session_delete", {"p_hash": digest(token)})
    response = JSONResponse({"ok": True})
    response.delete_cookie(cookie_name(COOKIE), path="/")
    return response
