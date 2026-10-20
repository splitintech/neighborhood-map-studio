# SplitIn Neighborhood Map Studio

A standalone owner-only editor and API for illustrated neighborhood maps. Both run in one Daytona container; Supabase Postgres and object storage hold durable state. Only GitHub accounts with the **verified email `splitineu@gmail.com`** can sign in. GitHub access tokens never reach the browser or storage.

The initial projects are San Francisco Mission and Boston Back Bay, exported from reviewed SplitIn source revision `925d14c4831554a406dff6f26814177d1c0fa487`. Canonical business IDs, addresses and locations are read-only. This repository does not replace SplitIn public pages or change their URLs.

## Local verification

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
# Linux SVG runtime dependency: apt-get install libcairo2
cd frontend
npm ci
npm run typecheck
npm test
npm run build
cd ..
.venv/bin/python -m pytest tests -q
node shared/tests/run-tests.mjs
node --test integrations/public-layers.test.mjs
```

Database tests require `MAP_STUDIO_TEST_DATABASE_URL` pointing to a **disposable local Postgres database**. Browser tests use mocked authenticated API fixtures and run with `cd frontend && npm run test:browser`; they do not establish production OAuth or database readiness.

Copy `.env.example` to `.env`, configure the secure environment values, apply migrations in numeric order using a database administrator, then run:

```sh
.venv/bin/python scripts/seed-pilot.py          # dry run
.venv/bin/python scripts/seed-pilot.py --apply  # explicit owner/project assignment
.venv/bin/python scripts/seed-artwork.py --apply # three original guide stickers per map
.venv/bin/python -m uvicorn server.map_studio.main:app --host 127.0.0.1 --port 3000
```

Open `/map-studio/`. Register a GitHub OAuth app with callback `<MAP_STUDIO_ORIGIN>/api/auth/callback`. The origin must remain stable across sandbox recreation. Store the OAuth client secret, session signing secret and Supabase service-role key only in server environment settings. Never put them in `VITE_*` values, Git, screenshots or logs.

## Storage setup

Apply `migrations/001_map_studio.sql`, `002_owner_sessions.sql`, then `003_public_delivery.sql` to the existing Supabase project after reviewing names/conflicts and taking a backup. The changes are confined to `map_studio_*` records and functions. Browser clients cannot access their tables directly. Privileged RPC calls receive an actor ID only from the server-validated session and explicitly check map membership.

Create these buckets using the Supabase dashboard or administrative API:

| Bucket | Visibility | Content |
| --- | --- | --- |
| `map-studio-private` | Private | Original uploads and optimized draft artwork |
| `map-studio-published` | Public | Content-hashed raster derivatives used in publications |

Do not add anonymous write policies or expose originals. Accept PNG, JPEG, WebP and SVG up to 5 MiB. SVG support is a deliberately restricted vector subset; scripts, linked resources, active content and unsupported tags are rejected. A credential-free child process has a 12-second deadline and Linux CPU/address-space/file limits. Raster derivatives preserve aspect ratio, strip original metadata and fit 2048px.

## Editing and publication

The editor includes real Leaflet navigation, tile consent, Terra Draw geometry, artwork and annotation properties, layers, undo/redo, preview, revision-checked saving, two-minute edit leases, version history and rollback. Numeric controls accompany movement gestures. Recovery lives in user/map-scoped IndexedDB and is cleared on explicit logout. It is not a server backup.

A lease is tied to a browser tab, not simply an account, so opening a second tab cannot silently overwrite the first. The backend checks lease and revision again at publication. Asset derivatives are hash-verified before the database atomically advances its publication pointer; a failed upload cannot replace the current version.

Public delivery is disabled initially. [`integrations/README.md`](integrations/README.md) documents the existing-page adapter. Published manifests can be read directly from Supabase through a narrow opt-in function, so public rendering does not wake or depend on Daytona. Existing source business cards and maps remain the fallback. The editor currently uses OSM raster tiles; the adapter retains the public pages' existing OpenFreeMap Canvas basemap.

## Deployment and operations

See [`docs/daytona.md`](docs/daytona.md) for the pinned image/snapshot, secrets, private/public preview distinction and restart procedure. Linking GitHub to Daytona provides account/repository access; it does not configure application OAuth, storage or a stable gateway.

See [`docs/operations.md`](docs/operations.md) for backup/restore, rollback, monitoring, budget and pilot acceptance. See [`docs/verification.md`](docs/verification.md) for actual local evidence and remaining deployment checks. WebGPU, Three.js and 3D are deferred.
