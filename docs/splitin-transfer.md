# SplitIn source transfer — 2026-10-22

This is a source-only relocation from `splitintech/open-internal-tools` PR20, immutable commit `87b71450ce3422ec80112de4c680f77775de6937`, into `services/neighborhood-map-studio/`. The original repository is preserved. Runtime implementation, dependencies, fixtures, SQL, shared renderer and historical integration patch are unchanged. Only repository-location documentation and workflow context/working-directory paths are adapted.

## Publication boundaries

- The three SQL files stay inside this service's `migrations/`, not the repository's automatic `supabase/migrations/` path. No remote database migration, seed, storage provisioning or public publication is performed by this transfer.
- Public API manifests and database public delivery remain disabled by default. No credentials, OAuth application, Daytona runtime, gateway or public map flags are configured.
- The existing public SplitIn map code is untouched. `integrations/splitin.patch` is historical and deferred; it requires reconciliation and regression tests against current SplitIn before future application.
- The verification workflow uses disposable localhost PostgreSQL and fixture APIs. Its Docker step builds only. The image-publishing workflow remains manual (`workflow_dispatch`) and does not provision or deploy Daytona.

## Transfer checks

Executed on the relocated service in an isolated temporary workspace:

- Frontend TypeScript check, six state tests and Vite production build passed. Build retains its existing >500 kB bundle-size warning.
- Eleven shared contract/renderer tests and three public-adapter tests passed.
- With exact project Python requirements installed, 42 Python tests passed; ten database tests skipped because `MAP_STUDIO_TEST_DATABASE_URL` was explicitly unset. No remote database was used.
- Initial tests using preinstalled mismatched Python dependencies had one SVG decoder failure; installing the project's declared requirements resolved it without source changes.
- Independent read-only path/defaults review found no relocation runtime-path blocker. Docker context, service-relative paths, explicit export source argument, dry-run provisioning/seeding and off-by-default public delivery were checked.
- New browser verification was blocked before Chromium launch by the executor's socket restriction (`Operation not permitted`). No browser result is claimed. No Docker daemon or local PostgreSQL was available. Original upstream CI evidence in `verification.md` is historical, not new transfer validation.

The existing repository workflows, hosting configuration and public application code are not modified. Main merges may trigger existing hosting deployments and repository checks; that does not activate this standalone service. Existing Stripe reconciliation uses a secret-selected signoff RPC; its deployed runtime was not exercised by local validation. Full application, deployed provider, physical-device, backup/restore, capacity and pilot acceptance remain separate launch work.
