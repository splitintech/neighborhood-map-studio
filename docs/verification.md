# Verification record — 2026-10-20

## Source and repository baseline

- Target: `splitintech/open-internal-tools`, verified remote main `3e34ca2cb722e5970b6659c1d48e00363c2ed315`; implementation isolated on `feat/neighborhood-map-studio`.
- Source inventory: SplitIn `925d14c4831554a406dff6f26814177d1c0fa487`; original dirty checkout untouched.
- Research source: 1,693 records; SF research publication projection: 1,442 places. These are distinct pipeline stages.
- Editorial source: 57 profiles, 364 listed memberships, 338 distinct canonical businesses across those profiles.
- Pilot expanded inventories: Mission 32 listings/31 mapped/1 address-only; Back Bay 25 listings/24 mapped/1 address-only. Both have zero off-map city references in this export.
- Fixture SHA-256: `1d968c3a84741164353fc6fb82c75a60c79e9a46397f1c88452c04e799db7ad5`.

## Local checks

- Frontend TypeScript, six state tests and production Vite build pass.
- Eleven shared contract/renderer tests pass, including coordinate bounds, complexity, canonical-business locking, plain-text annotations, pane lifecycle, integer CSS stacking and artwork rotation without replacing Leaflet translation.
- The public adapter passes a separate TypeScript check.
- Three public-adapter tests pass for exact pilot route matching, published-only retrieval, hidden-business suppression, filter changes and document replacement. The separate SplitIn patch applies cleanly at the recorded source baseline; its six focused tests and four affected entrypoint compilations pass. Patch SHA-256: `3a5616b5ca35e8115e724217de8261117bc3bdac6fe2c8bc45dfe1d6087ff8d`.
- Authentication and HTTP boundary tests reject unauthenticated draft/asset/lease/publication requests, forged sessions, wrong email verification, CSRF failures and cross-origin writes. OAuth state expiry/tampering/replay are covered with provider responses mocked.
- The final Python suite excluding native image processing passes 45 tests, including the eleven provisioning tests. Owner-only assignment, canonical pilot inventories and PostgREST composite return normalization are covered.
- Real PostgreSQL exercises migrations, service-role grants, denied anonymous access, lease expiry, revision CAS, publication/rollback idempotency, assets, audits and opted-in published-only external delivery.
- Seven image tests pass on native ARM Python 3.14 with Homebrew Cairo: raster decode, restricted SVG, aspect ratio, active/external-resource rejection, malformed files and 5 MiB limit. The API/database test runtime is Python 3.11.13; the release image targets Python 3.11/Linux. The Mac's Intel Python cannot load its ARM Cairo library, so image tests use the native interpreter.
- All three original starter SVGs successfully pass the rasterization pipeline.
- Eleven Daytona provisioning tests pass. SDK `daytona==0.225.0` was installed separately and actual method/resource/preview types inspected; no provider operations were performed.
- Pilot and artwork seed commands pass in dry-run mode.
- Chromium checks pass at 1440px desktop, 390px mobile and 900px tablet widths using mocked authenticated API responses: real Leaflet navigation, Terra Draw point creation, artwork placement, numeric resize/rotation, reorder, autosave, publish, CSRF headers and signed-out login. Screenshots were visually inspected. These are viewport checks, not physical Safari/Android or production OAuth tests.

## Not yet verified or enabled

No live Daytona sandbox, production OAuth app, remote migration, bucket provisioning, source seed or public-page rollout has occurred. Repository secret names were inspected and no deployment secrets were configured. Existing SplitIn public URLs and business pipeline remain unchanged.

A local Docker daemon/buildx is unavailable; CI contains a release-image build check but its result must be recorded separately. Production registry access, startup/sleep/recreation, stable authenticated gateway, backup restore and application rollback need account configuration and deployed evidence. Automatic waking requires infrastructure outside the sleeping sandbox.

Public integration is supplied as an adapter, an off-by-default durable projection and a separately applicable SplitIn source patch. The patch has not been applied to the user's checkout or deployed. Mobile physical devices, screen readers, performance baselines, 10-editor/100-viewer load, actual spending alerts/limits, restore rehearsal and seven-day pilot are outstanding acceptance evidence. Local source/unit/browser-fixture checks do not establish these measurements.
