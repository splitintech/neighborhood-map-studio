from __future__ import annotations

import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from server.map_studio import auth
from server.map_studio.config import OWNER_EMAIL, OWNER_ID, settings


def request(*, cookie: str | None = None, headers: dict[str, str] | None = None) -> Request:
    values = {"host": "studio.example"}
    if cookie:
        values["cookie"] = cookie
    values.update(headers or {})
    return Request({
        "type": "http", "method": "GET", "scheme": "https", "path": "/",
        "raw_path": b"/", "query_string": b"", "headers": [
            (key.lower().encode(), value.encode()) for key, value in values.items()
        ], "server": ("studio.example", 443), "client": ("127.0.0.1", 1),
    })


def configure(monkeypatch):
    monkeypatch.setattr(settings, "origin", "https://studio.example")
    monkeypatch.setattr(settings, "session_secret", "s" * 48)
    monkeypatch.setattr(settings, "github_client_id", "client")
    monkeypatch.setattr(settings, "github_client_secret", "secret")
    monkeypatch.setattr(settings, "session_hours", 8)


def test_owner_email_requires_verified_exact_owner(monkeypatch):
    monkeypatch.setattr(auth, "OWNER_EMAIL", OWNER_EMAIL)
    assert auth.owner_verified([{"email": " SPLITINEU@GMAIL.COM ", "verified": True}])
    assert not auth.owner_verified([{"email": OWNER_EMAIL, "verified": False}])
    assert not auth.owner_verified([{"email": "other@example.com", "verified": True}])


def test_signed_oauth_state_rejects_tampering_and_expiry(monkeypatch):
    configure(monkeypatch)
    signed = auth.sign_state({"state": "nonce", "verifier": "v", "created": time.time()})
    assert auth.read_state(signed)["state"] == "nonce"
    with pytest.raises(HTTPException) as tampered:
        auth.read_state(signed[:-1] + ("a" if signed[-1] != "a" else "b"))
    assert tampered.value.status_code == 400
    expired = auth.sign_state({"state": "nonce", "verifier": "v", "created": time.time() - 601})
    with pytest.raises(HTTPException) as stale:
        auth.read_state(expired)
    assert stale.value.detail == "oauth_state_invalid"


@pytest.mark.asyncio
async def test_actor_rejects_forged_session_and_enforces_csrf(monkeypatch):
    configure(monkeypatch)
    token = "t" * 48

    async def forged(_name, _args):
        return {"id": str(uuid4()), "email": OWNER_EMAIL, "csrfToken": "csrf"}

    monkeypatch.setattr(auth, "auth_rpc", forged)
    with pytest.raises(HTTPException) as error:
        await auth.actor(request(cookie=f"__Host-map-studio-session={token}"))
    assert error.value.status_code == 401

    async def valid(_name, _args):
        return {"id": OWNER_ID, "email": OWNER_EMAIL, "csrfToken": "csrf"}

    monkeypatch.setattr(auth, "auth_rpc", valid)
    with pytest.raises(HTTPException) as missing_csrf:
        await auth.actor(request(cookie=f"__Host-map-studio-session={token}"), write=True)
    assert missing_csrf.value.detail == "csrf_required"
    with pytest.raises(HTTPException) as wrong_origin:
        await auth.actor(request(cookie=f"__Host-map-studio-session={token}", headers={"origin": "https://evil.example", "x-csrf-token": "csrf"}), write=True)
    assert wrong_origin.value.detail == "origin_not_allowed"
    accepted = await auth.actor(request(cookie=f"__Host-map-studio-session={token}", headers={"origin": settings.origin, "x-csrf-token": "csrf"}), write=True)
    assert accepted["user"] == {"id": OWNER_ID, "email": OWNER_EMAIL}


class FakeGitHubClient:
    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return httpx.Response(200, json={"access_token": "provider-token"}, request=httpx.Request("POST", url))

    async def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        if url.endswith("/user"):
            return httpx.Response(200, json={"id": 12345}, request=httpx.Request("GET", url))
        return httpx.Response(200, json=[{"email": OWNER_EMAIL, "verified": True}], request=httpx.Request("GET", url))


@pytest.mark.asyncio
async def test_callback_consumes_oauth_state_once(monkeypatch):
    configure(monkeypatch)
    state, verifier = "oauth-state", "verifier"
    signed = auth.sign_state({"state": state, "verifier": verifier, "created": time.time()})
    consumed = []
    calls = []

    async def rpc(name, args):
        calls.append((name, args))
        if name == "map_studio_login_state_consume":
            consumed.append(True)
            return len(consumed) == 1
        return True

    monkeypatch.setattr(auth, "auth_rpc", rpc)
    monkeypatch.setattr(auth.httpx, "AsyncClient", FakeGitHubClient)
    first = await auth.callback(request(cookie=f"__Host-map-studio-oauth={signed}"), code="code", state=state)
    assert first.status_code == 303
    assert any(name == "map_studio_session_create" for name, _ in calls)
    with pytest.raises(HTTPException) as replay:
        await auth.callback(request(cookie=f"__Host-map-studio-oauth={signed}"), code="code", state=state)
    assert replay.value.detail == "oauth_state_expired_or_reused"


@pytest.mark.asyncio
async def test_callback_rejects_unverified_non_owner_email(monkeypatch):
    configure(monkeypatch)
    state = "owner-state"
    signed = auth.sign_state({"state": state, "verifier": "v", "created": time.time()})
    calls = []

    async def rpc(name, args):
        calls.append(name)
        return True

    class NonOwnerClient(FakeGitHubClient):
        async def get(self, url, **kwargs):
            if url.endswith("/user"):
                return httpx.Response(200, json={"id": 12345}, request=httpx.Request("GET", url))
            return httpx.Response(200, json=[{"email": "other@example.com", "verified": True}], request=httpx.Request("GET", url))

    monkeypatch.setattr(auth, "auth_rpc", rpc)
    monkeypatch.setattr(auth.httpx, "AsyncClient", NonOwnerClient)
    with pytest.raises(HTTPException) as error:
        await auth.callback(request(cookie=f"__Host-map-studio-oauth={signed}"), code="code", state=state)
    assert error.value.detail == "owner_account_required"
    assert "map_studio_session_create" not in calls
