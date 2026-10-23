# Optional SplitIn public-page integration

## Reconciled, not activated

`splitin.patch` is a reviewable optional integration against SplitIn main commit
`df1faf9fd77611de8565a26bff5b6011639050de`, read through the GitHub connector on
2026-10-23. It replaces the historical patch against `925d14c`.
The artifact is **not applied to the repository's public runtime**, and merging
this service does not activate public layers, apply migrations, or deploy anything.

`splitin-base.json` records the exact Git blob hashes of all five existing files
and SHA-256 of the patch. The eight new paths were verified absent at that commit.
Check a separate clean checkout before reviewing/applying:

```sh
python services/neighborhood-map-studio/integrations/verify-splitin-patch.py /path/to/clean/splitin
# Only in the separate integration checkout after reviewing the changes:
git apply services/neighborhood-map-studio/integrations/splitin.patch
cd packages/discovery-map
node --test tests/public-layers.test.mjs tests/studio-contracts.test.mjs tests/studio-host.test.mjs
```

The verifier is read-only: it checks the patch digest, exact base-file contents,
and `git apply --check`. A newer repository commit is acceptable only if those
base files are unchanged and the new paths remain absent. A mismatch stops the
check; reconcile rather than forcing the patch. The package tests require the
checkout's normal `esbuild` dependency.

## Preserved contracts

- Both public entrypoints retain the current neighborhood presentation, category
  navigation, source coordinates, canonical IDs, cards, routing and filters.
- The existing Leaflet provider, OpenFreeMap street layer, consent gate, reduced
  data behavior, selection, detail presentation and browser history remain owned
  by the host. The Studio request starts only after consent and map creation.
- Optional projection loading is asynchronous and does not delay street readiness.
  Failures leave existing cards and markers available. A map-generation guard
  prevents a response after close, revoke, suspension or replacement from mounting.
- The first overlay uses the current filtered/area snapshot, including changes
  made while fetching. Overlay selection calls the existing selection handler.
  Published business references suppress only their corresponding base marker;
  filter changes, disposal and map recreation release that suppression.
- The patch vendors the current service renderer/contracts and adapter. It adds
  no coordinates, changes no credentials and enables no feature flag.

## Separate rollout requirements

1. Review/apply the patch in an isolated checkout and complete host browser
   regressions before deploying it. Import the included shared CSS only once.
2. Set browser-safe `PUBLIC_MAP_STUDIO_SUPABASE_URL` and
   `PUBLIC_MAP_STUDIO_SUPABASE_ANON_KEY`. Use the public legacy anon JWT key,
   never the service-role key. The adapter reads only the published projection
   directly from Supabase and never calls Daytona.
3. Explicitly opt in each desired map with
   `PUBLIC_MAP_STUDIO_SAN_FRANCISCO_MISSION=true` or
   `PUBLIC_MAP_STUDIO_BOSTON_BACK_BAY=true`. Missing/other values stay off.
   Only exact `/blog/guides/{pilot-key}/places/` routes resolve automatically;
   category pages require an explicit matching `data-map-studio-key`.
4. Permit the configured Supabase origin in `connect-src` and `img-src` CSP.
   Only public hashed WebP derivatives are loaded, never originals or drafts.
5. After staging acceptance, an administrator separately enables
   `public_delivery_enabled` for the chosen map. Database delivery defaults off.

## Verification performed

- Exact GitHub source blobs verified and clean `git apply --check` passed.
- `node --test integrations/public-layers.test.mjs`: 7 passed.
- Patched package adapter, renderer/contracts and host tests: 14 passed.
- All three modified TypeScript entrypoints transpile with esbuild.
- `git diff --check`: passed.

Tests cover disabled defaults, per-map flags, source identity, published-only
requests, failures, late responses, filters, suppression and selection callbacks.
Host tests additionally assert integration ordering/lifecycle wiring. These are
unit/structural checks, not an end-to-end browser result or a full host typecheck.
Consent toggling during a request, close/reopen, both responsive presentations,
back/forward, category/area filtering, degraded streets and real Supabase delivery
still require staging browser acceptance before enabling the separate rollout.
