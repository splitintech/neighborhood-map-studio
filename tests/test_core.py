from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from server.map_studio import models, store


def record():
    return SimpleNamespace(id=uuid4(), user={"id": str(uuid4())})


def response(payload, status=200):
    return httpx.Response(status, json=payload)


def document(map_key="san-francisco-mission"):
    return {
        "schemaVersion": 1,
        "mapKey": map_key,
        "theme": "original",
        "layers": [{
            "id": "label", "kind": "annotation", "name": "Mission", "visible": True,
            "opacity": 1, "minZoom": 0, "maxZoom": 24, "text": "Mission", "position": [-122.4, 37.75],
        }],
    }


def test_layer_document_rejects_unknown_properties():
    value = document()
    value["layers"][0]["arbitraryMetadata"] = {"private": True}
    with pytest.raises(ValidationError):
        models.LayerDocument.model_validate(value)


@pytest.mark.asyncio
async def test_rpc_injects_verified_actor_and_never_client_credentials(monkeypatch):
    calls = []

    async def transport(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return response({"ok": True})

    monkeypatch.setattr(store, "supabase_request", transport)
    session = record()
    await store.rpc(session, "map_studio_get_project", {"p_map_key": "san-francisco-mission"})
    assert calls[0][1] == "/rest/v1/rpc/map_studio_get_project"
    assert calls[0][2]["json_body"] == {
        "p_map_key": "san-francisco-mission", "p_actor": str(session.id),
    }
    assert calls[0][2].get("access_token") is None
    assert calls[0][2].get("service_role") is None


@pytest.mark.asyncio
async def test_publish_passes_prepared_public_assets_to_atomic_rpc(monkeypatch):
    calls = []

    async def transport(method, path, **kwargs):
        calls.append((path, kwargs))
        return response({"version_id": str(uuid4())})

    monkeypatch.setattr(store, "supabase_request", transport)
    asset_id = uuid4()
    result = await store.publish(record(), "san-francisco-mission", 4, "client-a", "request-1", [{"id": str(asset_id)}])
    assert result["versionId"]
    assert calls[0][1]["json_body"] == {
        "p_map_key": "san-francisco-mission", "p_expected_revision": 4, "p_client_id": "client-a",
        "p_idempotency_key": "request-1", "p_assets": [{"id": str(asset_id)}],
        "p_actor": calls[0][1]["json_body"]["p_actor"],
    }


@pytest.mark.asyncio
async def test_rpc_maps_revision_conflict_without_leaking_provider_details(monkeypatch):
    async def transport(method, path, **kwargs):
        return response({"message": "revision_conflict internal SQL detail"}, 409)

    monkeypatch.setattr(store, "supabase_request", transport)
    with pytest.raises(Exception) as error:
        await store.rpc(record(), "map_studio_save_draft", {})
    assert error.value.status_code == 409
    assert error.value.detail == "map_studio_conflict"


@pytest.mark.asyncio
async def test_public_manifest_uses_anon_transport_without_browser_token(monkeypatch):
    calls = []
    monkeypatch.setattr(store.settings, "public_manifests_enabled", True)

    async def transport(method, path, **kwargs):
        calls.append(kwargs)
        return response({"version_id": str(uuid4()), "document": document(), "assets": []})

    monkeypatch.setattr(store, "supabase_request", transport)
    result = await store.public_manifest("san-francisco-mission")
    assert result["assets"] == []
    assert calls[0].get("access_token") is None and calls[0].get("service_role") is None


@pytest.mark.asyncio
async def test_public_manifest_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(store.settings, "public_manifests_enabled", False)

    async def transport(*args, **kwargs):
        raise AssertionError("disabled public manifests must not reach storage")

    monkeypatch.setattr(store, "supabase_request", transport)
    with pytest.raises(Exception) as error:
        await store.public_manifest("san-francisco-mission")
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_project_json_roundtrip_keeps_canonical_business_fields_only(monkeypatch):
    async def rpc(_record, name, _arguments):
        assert name == "map_studio_get_project"
        return {
            "project": {"map_key": "san-francisco-mission", "title": "Mission", "city": "San Francisco",
                        "public_path": "/maps/mission", "center": [-122.4, 37.75], "source_revision": "source-1"},
            "businesses": [{
                "id": "cafe-1", "name": "Cafe", "category": None,
                "location": {"lat": 37.75, "lng": -122.4, "precisionNote": "block", "sourceUrl": "private"},
                "logo_url": None, "sourceUrl": "private", "method": "geocoder",
            }],
            "draft": {"document": document(), "revision": 3}, "can_edit": True,
        }

    monkeypatch.setattr(store, "rpc", rpc)
    result = await store.get_project(record(), "san-francisco-mission")
    assert result["businesses"] == [{
        "id": "cafe-1", "name": "Cafe",
        "location": {"lat": 37.75, "lng": -122.4, "precisionNote": "block"},
    }]
    assert "sourceUrl" not in result["businesses"][0]
    assert "method" not in result["businesses"][0]


def test_migration_contains_auth_rls_and_atomic_guards():
    sql = open("migrations/001_map_studio.sql", encoding="utf-8").read()
    assert "alter table public.%I enable row level security" in sql
    assert "p_actor uuid" in sql
    assert "map_studio_owners" in sql
    assert "lease_conflict" in sql and "lease_required" in sql
    assert "revision_conflict" in sql and "idempotency_key" in sql
    assert "for update" in sql.lower()
    assert "map_studio_public_manifest" in sql
    assert "grant execute on function public.map_studio_register_project(jsonb,jsonb,jsonb,uuid,text) to service_role" in sql
    assert "grant execute on function public.map_studio_publish(text,bigint,text,text,jsonb,uuid) to service_role" in sql
    assert "grant execute on function public.map_studio_register_project(jsonb,jsonb,jsonb,uuid,text) to anon" not in sql
    assert "auth.uid()" not in sql
    # A migration for this feature must never revoke unrelated application RPCs.
    assert "revoke all on all functions in schema public" not in sql.lower()

@pytest.mark.asyncio
async def test_composite_asset_rpc_normalizes_postgrest_row_arrays(monkeypatch):
    async def transport(method, path, **kwargs):
        return response([{'id': 'asset-1', 'state': 'ready'}])
    monkeypatch.setattr(store, 'supabase_request', transport)
    assert await store.rpc(record(), 'map_studio_asset_get', {}) == {'id': 'asset-1', 'state': 'ready'}
    assert await store.rpc(record(), 'map_studio_asset_list', {}) == [{'id': 'asset-1', 'state': 'ready'}]
