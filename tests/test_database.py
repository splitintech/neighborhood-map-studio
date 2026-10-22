"""Opt-in PostgreSQL contract tests for the durable Map Studio boundary.

Set MAP_STUDIO_TEST_DATABASE_URL to a disposable PostgreSQL database.  The
tests apply the three checked-in migrations, create the three expected roles when
needed, and use the service-role RPC surface exactly as the standalone API
does.  With no URL configured the suite skips cleanly for frontend-only runs.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.types.json import Jsonb

from server.map_studio.config import OWNER_ID


DATABASE_URL = os.getenv("MAP_STUDIO_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="MAP_STUDIO_TEST_DATABASE_URL is not configured")

ROOT = os.path.dirname(os.path.dirname(__file__))
MIGRATIONS = [
    os.path.join(ROOT, "migrations", "001_map_studio.sql"),
    os.path.join(ROOT, "migrations", "002_owner_sessions.sql"),
    os.path.join(ROOT, "migrations", "003_public_delivery.sql"),
]
OWNER_EMAIL = "splitineu@gmail.com"


def connect(*, autocommit: bool = True):
    connection = psycopg.connect(DATABASE_URL, autocommit=autocommit)
    connection.execute("set role service_role")
    return connection


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
        admin.execute("create extension if not exists pgcrypto")
        admin.execute("""
            do $$ begin
              if not exists (select 1 from pg_roles where rolname='anon') then create role anon; end if;
              if not exists (select 1 from pg_roles where rolname='authenticated') then create role authenticated; end if;
              if not exists (select 1 from pg_roles where rolname='service_role') then create role service_role; end if;
            end $$;
        """)
        for path in MIGRATIONS:
            with open(path, encoding="utf-8") as migration:
                admin.execute(migration.read())
    yield


@contextmanager
def service_connection():
    connection = connect()
    try:
        yield connection
    finally:
        connection.close()


def project_fixture(connection, *, key: str | None = None):
    owner = UUID(OWNER_ID)
    map_key = key or f"test-{uuid4().hex[:20]}"
    project = {
        "mapKey": map_key, "title": "Database Test", "city": "San Francisco",
        "publicPath": f"/maps/{map_key}", "center": [-122.42, 37.76],
        "sourceRevision": "test-source", "ownerId": str(owner),
    }
    document = {"schemaVersion": 1, "mapKey": map_key, "theme": "original", "layers": []}
    connection.execute(
        "select public.map_studio_register_project(%s::jsonb,%s::jsonb,%s::jsonb,%s::uuid,%s)",
        (Jsonb(project), Jsonb([]), Jsonb(document), owner, OWNER_EMAIL),
    ).fetchone()
    return map_key, owner, document


def call(connection, name: str, *args):
    placeholders = ",".join(["%s"] * len(args))
    return connection.execute(f"select public.{name}({placeholders})", args).fetchone()[0]


def assert_sqlstate(error, state: str):
    assert getattr(error.value, "sqlstate", None) == state, str(error.value)


def audit_actions(map_key: str) -> set[str]:
    # The service role intentionally has no direct table grants; this read uses
    # the test administrator connection solely to inspect the audit evidence.
    with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
        return {row[0] for row in admin.execute(
            "select action from public.map_studio_audit_events where map_key=%s", (map_key,)
        ).fetchall()}


def test_migrations_expose_only_service_rpc_and_deny_anon():
    with service_connection() as connection:
        map_key, owner, _ = project_fixture(connection)
        project = call(connection, "map_studio_get_project", map_key, owner)
        assert project["project"]["mapKey"] == map_key

    with psycopg.connect(DATABASE_URL, autocommit=True) as anonymous:
        anonymous.execute("set role anon")
        with pytest.raises(Exception) as error:
            call(anonymous, "map_studio_get_project", map_key, owner)
        assert_sqlstate(error, "42501")


def test_owner_only_assignment_and_lease_expiry_between_tabs():
    with service_connection() as connection:
        map_key, owner, _ = project_fixture(connection)
        second = uuid4()
        with pytest.raises(Exception) as denied:
            call(connection, "map_studio_set_member", map_key, second, True, owner)
        assert_sqlstate(denied, "42501")
        call(connection, "map_studio_acquire_lease", map_key, "first-client", owner)
        with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
            admin.execute("update public.map_studio_leases set expires_at=now()-interval '1 second' where map_key=%s", (map_key,))
        lease = call(connection, "map_studio_acquire_lease", map_key, "second-client", owner)
        assert lease["clientId"] == "second-client"
        call(connection, "map_studio_disable_project", map_key, owner)
        with pytest.raises(Exception) as error:
            call(connection, "map_studio_acquire_lease", map_key, "after-disable", owner)
        assert_sqlstate(error, "P0002")


def test_stale_publication_and_idempotency_fingerprint_are_atomic():
    with service_connection() as connection:
        map_key, owner, document = project_fixture(connection)
        call(connection, "map_studio_acquire_lease", map_key, "publisher", owner)
        call(connection, "map_studio_save_draft", map_key, Jsonb(document), 0, "publisher", owner)
        with pytest.raises(Exception) as stale:
            call(connection, "map_studio_publish", map_key, 0, "publisher", "pub-1", Jsonb([]), owner)
        assert_sqlstate(stale, "40001")
        published = call(connection, "map_studio_publish", map_key, 1, "publisher", "pub-1", Jsonb([]), owner)
        repeated = call(connection, "map_studio_publish", map_key, 1, "publisher", "pub-1", Jsonb([]), owner)
        assert repeated == published
        with pytest.raises(Exception) as reused:
            call(connection, "map_studio_publish", map_key, 1, "different-client", "pub-1", Jsonb([]), owner)
        assert_sqlstate(reused, "40001")
        assert "publish" in audit_actions(map_key)


def test_rollback_restores_document_and_published_pointer():
    with service_connection() as connection:
        map_key, owner, original = project_fixture(connection)
        call(connection, "map_studio_acquire_lease", map_key, "rollback-client", owner)
        first = call(connection, "map_studio_publish", map_key, 0, "rollback-client", "publish-original", Jsonb([]), owner)
        changed = {**original, "theme": "paper"}
        call(connection, "map_studio_save_draft", map_key, Jsonb(changed), 0, "rollback-client", owner)
        rolled = call(connection, "map_studio_rollback", map_key, UUID(first["version_id"]), "rollback-client", "rollback-1", owner)
        assert rolled["version_id"] == first["version_id"]
        detail = call(connection, "map_studio_get_project", map_key, owner)
        assert detail["draft"]["document"] == original
        assert "rollback" in audit_actions(map_key)


def test_asset_reference_guard_and_audit_rows():
    with service_connection() as connection:
        map_key, owner, document = project_fixture(connection)
        asset_id = uuid4()
        digest = "b" * 64
        original_path = f"{map_key}/{asset_id}/original"
        processed_path = f"{map_key}/{asset_id}/{digest}.webp"
        row = call(connection, "map_studio_asset_register", map_key, Jsonb({
            "id": str(asset_id), "name": "marker", "alt_text": "Marker", "rights": "owned",
            "mime_type": "image/webp", "sha256": digest, "original_path": original_path,
            "processed_path": processed_path, "width": 16, "height": 16, "byte_size": 10, "state": "ready",
        }), owner)
        assert row is not None
        call(connection, "map_studio_acquire_lease", map_key, "asset-client", owner)
        referenced = {**document, "layers": [{
            "id": "art", "kind": "artwork", "name": "Marker", "visible": True, "opacity": 1,
            "minZoom": 0, "maxZoom": 24, "assetId": str(asset_id), "position": [-122.42, 37.76],
            "width": 16, "height": 16,
        }]}
        call(connection, "map_studio_save_draft", map_key, Jsonb(referenced), 0, "asset-client", owner)
        with pytest.raises(Exception) as referenced_error:
            call(connection, "map_studio_asset_delete", map_key, asset_id, owner)
        assert_sqlstate(referenced_error, "40901")
        call(connection, "map_studio_save_draft", map_key, Jsonb(document), 1, "asset-client", owner)
        assert call(connection, "map_studio_asset_delete", map_key, asset_id, owner)["ok"]
        assert {"asset_register", "asset_delete"}.issubset(audit_actions(map_key))


def test_session_rpc_rejects_forged_owner_and_expires():
    with service_connection() as connection:
        token_hash = "c" * 64
        csrf = "csrf-token"
        assert call(connection, "map_studio_session_create", token_hash, UUID(OWNER_ID), OWNER_EMAIL, "github-1", csrf, 1)
        session = call(connection, "map_studio_session_get", token_hash)
        assert session["id"] == OWNER_ID and session["email"] == OWNER_EMAIL
        with pytest.raises(Exception) as forged:
            call(connection, "map_studio_session_create", "d" * 64, UUID(OWNER_ID), "other@example.com", "github-2", csrf, 1)
        assert_sqlstate(forged, "42501")
        with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
            admin.execute("update public.map_studio_sessions set expires_at=now()-interval '1 second' where token_hash=%s", (token_hash,))
        assert call(connection, "map_studio_session_get", token_hash) is None


def test_anonymous_delivery_is_opt_in_and_never_reads_draft_or_private_asset_fields():
    with service_connection() as connection:
        map_key, owner, document = project_fixture(connection)
        asset_id = uuid4()
        digest = "d" * 64
        call(connection, "map_studio_asset_register", map_key, Jsonb({
            "id": str(asset_id), "name": "published marker", "alt_text": "Marker", "rights": "owned",
            "mime_type": "image/webp", "sha256": digest,
            "original_path": f"{map_key}/{asset_id}/original",
            "processed_path": f"{map_key}/{asset_id}/{digest}.webp",
            "width": 24, "height": 24, "byte_size": 12, "state": "ready",
        }), owner)
        call(connection, "map_studio_acquire_lease", map_key, "delivery-client", owner)
        published_document = {**document, "theme": "paper", "layers": [{
            "id": "published-art", "kind": "artwork", "name": "Marker", "visible": True,
            "opacity": 1, "minZoom": 0, "maxZoom": 24, "assetId": str(asset_id),
            "position": [-122.42, 37.76], "width": 24, "height": 24,
        }]}
        call(connection, "map_studio_save_draft", map_key, Jsonb(published_document), 0, "delivery-client", owner)
        call(connection, "map_studio_publish", map_key, 1, "delivery-client", "delivery-publish", Jsonb([{"id": str(asset_id)}]), owner)
        # A later draft is private and must not change the durable public pointer.
        draft_document = {**published_document, "theme": "sage", "layers": []}
        call(connection, "map_studio_save_draft", map_key, Jsonb(draft_document), 1, "delivery-client", owner)
        with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
            admin.execute("update public.map_studio_projects set public_delivery_enabled=true where map_key=%s", (map_key,))

    with psycopg.connect(DATABASE_URL, autocommit=True) as anonymous:
        anonymous.execute("set role anon")
        manifest = call(anonymous, "map_studio_delivery_manifest", map_key)
        assert set(manifest) == {"versionId", "document", "assets"}
        assert manifest["document"] == published_document
        assert manifest["document"] != draft_document
        assert len(manifest["assets"]) == 1
        asset = manifest["assets"][0]
        assert {"id", "name", "altText", "rights", "publicPath", "width", "height", "state"}.issubset(asset)
        assert "original_path" not in asset and "processed_path" not in asset
        assert asset["publicPath"] == f"{digest}.webp"


def test_anonymous_delivery_returns_no_row_before_enablement():
    with service_connection() as connection:
        map_key, _, _ = project_fixture(connection)
    with psycopg.connect(DATABASE_URL, autocommit=True) as anonymous:
        anonymous.execute("set role anon")
        assert call(anonymous, "map_studio_delivery_manifest", map_key) is None


def test_concurrent_saves_have_one_compare_and_swap_winner():
    with service_connection() as connection:
        map_key, owner, document = project_fixture(connection)
        call(connection, "map_studio_acquire_lease", map_key, "shared-client", owner)

    def save(theme: str):
        with service_connection() as concurrent:
            value = {**document, "theme": theme}
            try:
                return ("ok", call(concurrent, "map_studio_save_draft", map_key, Jsonb(value), 0, "shared-client", owner))
            except Exception as error:  # psycopg maps SQLSTATE 40001 to a driver subclass
                return (getattr(error, "sqlstate", None), None)

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(save, ("paper", "sage")))
    assert sum(result[0] == "ok" for result in outcomes) == 1
    assert sum(result[0] == "40001" for result in outcomes) == 1

def test_exported_pilots_preserve_mapped_and_address_only_inventory():
    import json
    from pathlib import Path
    fixture = json.loads((Path(ROOT) / 'fixtures/pilot.json').read_text())
    with service_connection() as connection:
        for project in fixture['projects']:
            call(connection, 'map_studio_register_project', Jsonb(project), Jsonb(project['businesses']),
                 None, UUID(OWNER_ID), OWNER_EMAIL)
            detail = call(connection, 'map_studio_get_project', project['mapKey'], UUID(OWNER_ID))
            assert len(detail['businesses']) == project['inventory']['listed']
            assert sum(bool(b['location']) for b in detail['businesses']) == project['inventory']['mapped']
            assert {b['id'] for b in detail['businesses']} == {b['id'] for b in project['businesses']}
