# Operations and launch gates

## Backups and restore

Use the existing Supabase project backup/PITR schedule for metadata and separately back up both artwork buckets with versioned storage and restricted operator access. Supabase database backups do not substitute for object bytes. Retain every published version and its assets throughout the pilot. Deleting an asset from the editor is a metadata tombstone; garbage collection is intentionally not automated.

Restore rehearsal: create an isolated database/storage target, apply migrations, restore all `map_studio_*` metadata and both buckets, compare row counts and referenced object SHA-256 values, seed no new drafts, and verify an owner login plus a published version. Record recovery time and missing references. Never restore over production to test recovery. Provider backup credentials and exports remain private.

Content rollback selects a previously validated version, changes the pointer and advances the draft revision. Application rollback deploys a previous image digest/snapshot without rolling back durable data. Forward-compatible schema migrations are retained; take a backup before any incompatible schema change. Deleted/unrecoverable Daytona sandboxes can be recreated from the same snapshot and secure app configuration.

## Runtime availability

The API and editor share the sandbox. A stopped sandbox cannot run its own wake-up endpoint. Use an external authenticated wake gateway or the Daytona dashboard/provisioning command. Do not promise automatic cold-start progress until a stable gateway has been configured and tested. A public Daytona preview still requires application GitHub login for every private API/asset request; public transport alone is not owner authorization. Private preview requires Daytona transport authentication in addition to app login.

## Monitoring and budget

Record route/status/duration and aggregate save/conflict/publish/asset/startup counts; never log tokens, cookies, authorization headers, query strings from OAuth callbacks, documents or upload contents. Use provider logs and storage/database metrics. Configure account alerts at $60, $80 and $90 incremental monthly usage. The scripts provision one named instance, but billing alerts and spending controls must be configured in the actual account; a configuration field is not a spending cap.

Planning allocation: Daytona $30, API/gateway $20, storage/database/delivery $25, monitoring/backups $10, contingency $15. At the plan's cited rates, 200 active hours of 1 vCPU/1 GiB compute is about $13.32, excluding other charges. Verify current billing and existing plan headroom before enabling. No measured cost claim or reliance on trial credits.

## Pilot acceptance record

Before launch, establish a stable authenticated origin and production OAuth app; run migrations and source seed; rehearse backup restore; configure storage buckets; build and scan the release image; verify owner and rejected-account sessions; test sandbox startup/stop/recreation. Wire the public adapter in the separate SplitIn deployment before enabling either per-map rollout switch.

Capture existing mobile/desktop map navigation, filtering, map/list selection, history, source links, attribution, consent, accessibility and load timings. These are the regression baseline; the fixture inventory alone is not a performance baseline.

On physical iPhone Safari and Android Chrome test select/place/move/resize/rotate/reorder, non-drag controls, save, publish, rollback, airplane-mode recovery, expired session, multiple tabs and orientation change. Run keyboard/screen-reader/200% zoom/contrast/reduced-motion checks. Test 10 concurrent maps/editors with separate permitted test identities only in a test environment (production remains owner-only) and 100 public viewers. Measure warm usability <3s, saves <1s, 30fps interaction, public load regression <=10%, publication visibility <=60s. Run a seven-day pilot and record defects, provider usage and expansion decision. None of these deployed/device measurements is implied by local tests.

Official references: [Daytona proxy](https://www.daytona.io/docs/en/custom-preview-proxy/), [preview authentication](https://www.daytona.io/docs/en/preview/), [persistence](https://www.daytona.io/docs/en/persistence/), [Supabase storage access](https://supabase.com/docs/guides/storage/security/access-control), [bucket visibility](https://supabase.com/docs/guides/storage/buckets/fundamentals), [GitHub OAuth](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps), [Leaflet](https://leafletjs.com/reference.html), [Terra Draw](https://github.com/JamesLMilner/terra-draw), [WCAG 2.2](https://www.w3.org/TR/WCAG22/), [OSM tile policy](https://operations.osmfoundation.org/policies/tiles/).
