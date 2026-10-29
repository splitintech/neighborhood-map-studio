# Local build and Daytona handoff

These are operator instructions, not an automatic deployment. Source publication does not run them. Keep public delivery disabled throughout private setup. Run commands from `services/neighborhood-map-studio/` unless stated otherwise.

## 1. Build and verify locally

Use Python 3.11 and Node 22, with an isolated Python environment (not the existing BFF environment). Linux SVG processing requires libcairo2. Follow README dependency installation, then:

```sh
cd frontend
npm ci --ignore-scripts
npm run typecheck && npm test && npm run build
cd ..
env -u MAP_STUDIO_TEST_DATABASE_URL python -m pytest tests -q
node shared/tests/run-tests.mjs
node --test integrations/public-layers.test.mjs
python scripts/preflight.py
```

Unset `MAP_STUDIO_TEST_DATABASE_URL` for offline tests. The database suite applies migrations to its configured URL: use it only with a freshly created disposable localhost PostgreSQL database, never production or a shared staging database. Skipped DB tests are not a DB pass. CI uses its own disposable PostgreSQL service.

Preflight is offline, reports migration SHA-256 values and built frontend presence, and makes zero provider calls. Keep the commit, preflight result and final image digest together in a private release record.

## 2. Prepare storage manually

Confirm the correct Supabase project and administrator connection, review object-name conflicts and the project's actual migration ledger, and take a database plus artwork backup before any change. Run `scripts/database-preflight.sql` using a secure local psql connection or dashboard SQL editor. It reads catalogs/bucket visibility only; review results rather than treating them as automatic approval.

The service-local files are NOT registered in the root Supabase migration runner. Apply exactly these files once, in this order, under your administrator workflow:

1. `migrations/001_map_studio.sql`
2. `migrations/002_owner_sessions.sql`
3. `migrations/003_public_delivery.sql`

For psql, use `--set ON_ERROR_STOP=1 --single-transaction --file <file>` for each file. Use a secure connection/service profile; do not put passwords in shell history. Record filename, SHA-256, target, time and result in your migration ledger. Do not blindly rename or reapply an already-recorded migration. These scripts are not a general reconciliation/rollback engine for partially applied or divergent schemas; inspect and repair unexpected state before continuing.

Create `map-studio-private` as PRIVATE and `map-studio-published` as PUBLIC. Public storage is only for content-hashed processed WebP derivatives; never originals. Do not grant anonymous writes or direct private-table reads. Run the read-only preflight again, verify expected RPC grants/RLS, and rehearse restore on a separate target.

## 3. Configure owner login and app environment

Choose a stable HTTPS Studio origin. Register the GitHub OAuth app callback at `<origin>/api/auth/callback`; scopes are `read:user user:email`. The application admits only the account with verified `splitineu@gmail.com`. This is separate from signing into Daytona with GitHub.

Put the six values from `.env.example` into your secure application environment. `MAP_STUDIO_SESSION_SECRET` needs at least 32 nonblank characters. Keep `MAP_STUDIO_PUBLIC_MANIFESTS_ENABLED=false`. Do not place server secrets in `VITE_*`, Git, browser configuration, screenshots, build arguments or logs. An explicit `MAP_STUDIO_ENVIRONMENT=development` allows localhost HTTP for local work only; production requires HTTPS.

```sh
python scripts/preflight.py --require-config
```

This checks local syntax/presence only, not remote credentials. The app's `/healthz` means process alive. `/readyz` additionally requires configured app values and the frontend bundle; it does NOT prove migrations, bucket policy, OAuth exchange or provider availability. Complete a real owner login and rejected-account check after deployment.

After reviewing the recorded pilot source revision, use `seed-pilot.py` and `seed-artwork.py` dry runs. Use `python scripts/seed-pilot.py` and `python scripts/seed-artwork.py`. Run their `--apply` forms only when you intend those writes. They do not enable public delivery.

## 4. Package and start Daytona

From repository root, Docker context MUST be the service folder:

```sh
docker build -f services/neighborhood-map-studio/Dockerfile \
  -t neighborhood-map-studio:local services/neighborhood-map-studio
```

The image runs non-root on port 3000. It contains frontend output and API code, not credentials, local test outputs or database state. The image health check probes local readiness.

The manual `Map Studio release image` workflow can publish a Linux image on a reviewed commit. Alternatively publish your locally verified image through your approved registry workflow. Record its immutable `@sha256:` digest; ensure Daytona can pull the package. Do not use a mutable tag for snapshot creation.

Use an isolated environment with `requirements-daytona.txt` for control-plane scripts. See `daytona.md` for snapshot and provisioning commands. Export the required settings securely for those control-plane scripts; unlike the application, they do not load `.env` automatically. Both default to dry-run; `--apply` is the explicit live-operation boundary. Keep the Daytona control-plane API key out of the application container. Reusing a named runtime requires matching image/snapshot, origin and application settings; mismatches require deliberate operator replacement rather than silently preserving stale configuration.

Private transport is the default. For browser OAuth, use a stable authenticated gateway or explicitly reviewed public transport with the application's owner-login boundary. Public transport does not grant access to drafts. A sleeping sandbox cannot wake itself: use the Daytona dashboard/provisioning command or a separately configured external authenticated wake gateway. Public maps read Supabase directly and do not wake Daytona.

## 5. Private acceptance, then optional public rollout

Verify startup, idle stop/restart, recreation from the pinned image, owner login/rejection, both pilot inventories, artwork upload, save/conflict handling, publish and version rollback. Check backups/restore, real devices/accessibility, resource use and actual billing controls. A readiness response or fixture test is not this acceptance.

`integrations/README.md` describes the separately applicable public-page patch and its verified source baseline. Apply/review it in an isolated checkout and run its tests before deployment. Public frontend per-map flags and database `public_delivery_enabled` remain off until explicitly enabled after staging acceptance. The optional Studio API manifest flag is separate from the direct-Supabase adapter. Start with one pilot and retain existing source cards/maps as fallback.

Content rollback selects a prior published version. Runtime rollback uses a prior image/snapshot while keeping durable data. Do not undo schema migrations or delete buckets as a runtime rollback. Revert per-map public switches to disable new overlays without removing canonical business cards.
