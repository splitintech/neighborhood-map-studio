<p align="center"><img src="docs/brand/splitin-logo.png" alt="SplitIn" width="96" height="96"></p>

# Neighborhood Map Studio

An OpenStreetMap-based editor for illustrated neighborhood maps: place artwork and
annotations, draw geometry, organize layers, preview changes and publish versioned overlays.
The initial projects are San Francisco Mission and Boston Back Bay.

## What this repository contains

This is the canonical standalone application, consolidating the original Open Internal
Tools implementation and subsequent committed SplitIn readiness fixes. It includes a
React/Leaflet editor, Python/FastAPI API, shared TypeScript renderer/contracts, service-local
SQL migrations, fixtures and Daytona/container tooling. Both source histories are retained.

**Distribution:** the full application runs as a service/container. The frontend remains
private and there is no newly published Map Studio npm package. The shared renderer and
contracts are potential library boundaries; extracting them into supported npm packages
is separate work. This migration does not change existing public SplitIn pages.

## Features and current boundaries

- Leaflet navigation over OSM raster tiles, loaded after user consent.
- Terra Draw points, lines and polygons; artwork and annotation controls.
- Layers, themes, undo/redo, preview and revision-checked saves.
- Per-tab edit leases, recovery in user/map-scoped IndexedDB and version rollback.
- Processed artwork derivatives and atomic publication-pointer updates.
- Public overlays designed to load from durable storage without waking the editor.

Canonical business IDs, addresses and locations remain read-only. The current login is
GitHub OAuth restricted to the configured owner identity in `server/map_studio/auth.py`;
it is not a general multi-user SplitIn-account integration. Public delivery starts disabled.
Live OAuth, storage, Daytona deployment and pilot acceptance require separate qualification.
WebGPU, Three.js and 3D are deferred.

## Architecture

```text
Browser editor (React + Leaflet + Terra Draw)
    -> FastAPI session/auth, editing and publication API
    -> Supabase Postgres + private originals/public processed artwork

Public map adapter -> published manifests/storage
                      (independent of the sleeping editor container)
```

The editor uses OpenStreetMap raster tiles. The existing-page adapter retains those
pages' OpenFreeMap Canvas basemap. Application annotations belong to the overlay data;
they do not edit the OpenStreetMap database.

## Prerequisites and local build

Use Python 3.11, Node.js 22 or later, npm, and Cairo for SVG processing
(`libcairo2` on Linux). Use an isolated Python environment.

```sh
git clone https://github.com/splitintech/neighborhood-map-studio.git
cd neighborhood-map-studio
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
cd frontend
npm ci --ignore-scripts
npm run typecheck
npm test
npm run build
cd ..
env -u MAP_STUDIO_TEST_DATABASE_URL python -m pytest tests -q
node shared/tests/run-tests.mjs
node --test integrations/public-layers.test.mjs
python scripts/preflight.py
```

Without `MAP_STUDIO_TEST_DATABASE_URL`, database tests skip. For full database checks,
point it only at a disposable local PostgreSQL database: the tests apply migrations.
CI supplies its own disposable database, runs the fixture browser journey and builds
and probes the container without provider network access.

## Configuration and local server

Copy `.env.example` to `.env` and configure server values:

| Variable | Purpose |
| --- | --- |
| `MAP_STUDIO_ENVIRONMENT` | Production by default; explicit development permits localhost HTTP |
| `MAP_STUDIO_ORIGIN` | Stable application origin and OAuth redirect base |
| `MAP_STUDIO_GITHUB_CLIENT_ID`, `MAP_STUDIO_GITHUB_CLIENT_SECRET` | GitHub OAuth application credentials |
| `MAP_STUDIO_SESSION_SECRET` | At least 32 nonblank characters for sessions |
| `MAP_STUDIO_SUPABASE_URL`, `MAP_STUDIO_SUPABASE_SERVICE_ROLE_KEY` | Server-side durable storage access |
| `MAP_STUDIO_PUBLIC_MANIFESTS_ENABLED` | Optional public API; keep false during private setup |

For local HTTP, set `MAP_STUDIO_ENVIRONMENT=development` and
`MAP_STUDIO_ORIGIN=http://127.0.0.1:3000`. Register the OAuth callback at
`<origin>/api/auth/callback`. Keep server secrets out of browser/Vite configuration.

```sh
python scripts/preflight.py --require-config
python -m uvicorn server.map_studio.main:app --host 127.0.0.1 --port 3000
```

Open `http://127.0.0.1:3000/map-studio/` when using the local origin.
`/healthz` proves process liveness. `/readyz` additionally checks local configuration
and frontend build presence; neither proves remote OAuth, database or storage readiness.

## Database, artwork and seeding

Review and apply the following service-local SQL files in order under your database
administration process. They are not automatically applied when this repository is cloned
or the container starts:

1. `migrations/001_map_studio.sql`
2. `migrations/002_owner_sessions.sql`
3. `migrations/003_public_delivery.sql`

Use [database preflight](scripts/database-preflight.sql) and the
[operator handoff](docs/local-daytona-release.md) to review existing state, grants and backups.
Create `map-studio-private` as a private bucket and `map-studio-published` as public for
processed content-hashed derivatives only. Do not expose original uploads.

Uploads support PNG, JPEG, WebP and a restricted SVG subset up to 5 MiB. Processing strips
metadata, bounds dimensions and isolates SVG decoding. Draft recovery in the browser
is not a durable backup.

`python scripts/seed-pilot.py` and `python scripts/seed-artwork.py` default to dry-run.
Their `--apply` forms write data. Review fixture provenance and owner assignments first.

## Container and Daytona deployment

Build from this repository root:

```sh
docker build -t neighborhood-map-studio:local .
```

The image runs as a non-root user on port 3000. It contains the built frontend and API;
credentials and durable database/artwork state stay outside the image. Image publication
is manual and disabled until `IMAGE_PUBLISHING_ENABLED` is configured.

Use [Daytona setup](docs/daytona.md) and [local release handoff](docs/local-daytona-release.md)
for immutable image digests, snapshots, environment configuration, private transport,
restart and acceptance. The control-plane scripts default to dry-run. A sleeping editor
requires an external wake mechanism; public map reads must not depend on it.

## Public integration and rollback

[integrations/README.md](integrations/README.md) documents the existing-page adapter and
pinned SplitIn patch baseline. Reconcile that patch with the consumer application before
applying it. Per-map public flags, the database public-delivery switch and the optional
Studio API manifest flag are distinct controls and remain off by default.

Keep existing source maps/cards as fallback. Content rollback selects a previous published
version; runtime rollback selects a previous image while retaining durable data. See
[operations](docs/operations.md) for backup/restore and pilot checks.

## Repository guide

| Path | Responsibility |
| --- | --- |
| `frontend` | Private React editor, build and fixture browser tests |
| `server/map_studio` | Authentication, API, validation and publication |
| `shared` | TypeScript contracts, Leaflet renderer and styles |
| `migrations` | Service-local schema and access controls |
| `integrations` | Public-page adapter, patch and verification |
| `scripts` | Preflight, export, seeding and Daytona operations |
| `tests` | Python unit, database and readiness checks |
| `docs` | Operations, historical verification and migration records |

Historical verification documents describe their original snapshots. Use the new migration
validation record for checks run against this standalone repository.

## Contributing and provenance

See [CONTRIBUTING.md](CONTRIBUTING.md), [migration provenance](docs/migration.md),
[validation record](docs/migration/validation.json), and [release setup](docs/repository-release.md).
Relevant Git history, source inventories, original licenses and artwork are retained.
The migration does not publish packages, configure credentials or deploy infrastructure.

## License

MIT. See [LICENSE](LICENSE).
