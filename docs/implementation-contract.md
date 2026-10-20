# Map Studio implementation contract

Source inventory: SplitIn revision `925d14c4831554a406dff6f26814177d1c0fa487`.
Implementation: `open-internal-tools/neighborhood-map-studio/`.

## Shared document

`LayerDocument = {schemaVersion: 1, mapKey: string, theme: "original" | "paper" | "sage", layers: StudioLayer[]}`.
Layer array order is drawing order. Common properties: `id`, `kind`, `name`,
`visible`, `opacity` (0..1), `minZoom`, `maxZoom`, optional `category`.
Coordinates always `[longitude, latitude]`.

- artwork: `assetId`, `position`, `width`, `height` (pixels), `rotation` (degrees).
- annotation: `text`, `position`.
- geometry: `geometry` (GeoJSON Point, LineString, or Polygon).
- business: `businessId`, optional `assetId`, `highlight: "none" | "accent" | "ring"`.
  No contributor coordinates or business metadata. `visible:false` hides only its map marker.

Canonical business view: `{id,name,category?,location?:{lat,lng,precisionNote?},logoUrl?}`.
Asset view: `{id,name,altText,rights,url,width,height,state:"ready"}`.
Project: `{mapKey,title,city,publicPath,center:[lng,lat],sourceRevision}`.
Use map keys `san-francisco-mission` and `boston-back-bay` for pilots.

Shared package exports in `shared/`:
`contracts.ts` exports above types, `validateLayerDocument(input)` returns document
or throws, `emptyLayerDocument(mapKey)`; `leaflet.ts` exports
`mountStudioLayers({L,map,document,businesses,assets,onSelect?,onMove?,editable?})`
returning `{update({document,businesses,assets,editable?}),dispose()}`.
Assets supplied as arrays; document validation rejects extra/unsupported properties.

## Standalone API protocol

Base `/api/bff/map-studio`. Owner-only GitHub cookie/CSRF session, no browser bearer tokens.
JSON errors use standard FastAPI detail; browser should show meaningful messages.

- GET `/projects` -> `{projects: Project[], isAdmin:boolean}`
- GET `/projects/{key}` -> `{project,businesses,draft:{document,revision},canEdit:true}`
- POST `/projects/{key}/lease` `{clientId}` -> `{clientId,expiresAt}`
- POST `/projects/{key}/lease/release` `{clientId}` -> `{ok:true}`
- POST `/projects/{key}/draft` `{document,expectedRevision,clientId}` -> `{revision,document}`
- GET `/projects/{key}/versions` -> `{versions:[{id,createdAt,createdBy,revision}],publishedVersionId}`
- POST `/projects/{key}/publish` `{expectedRevision,clientId}` with Idempotency-Key -> `{versionId}`
- POST `/projects/{key}/rollback` `{versionId,clientId}` with Idempotency-Key -> `{versionId}`
- GET `/projects/{key}/assets` -> `{assets: Asset[]}`
- POST `/projects/{key}/assets` `{name,altText,rights,mimeType,dataBase64}` -> `{asset:Asset}`
- GET `/projects/{key}/assets/{id}/content` -> private processed bytes
- POST `/projects/{key}/assets/{id}/delete` -> `{ok:true}` (reject referenced assets)
- admin POST `/projects/{key}/members` `{userId,enabled}` -> `{ok:true}`
- admin POST `/projects/{key}/disable` -> `{ok:true}`

Public GET `/api/public/map-studio/{key}` ->
`{versionId,document,assets:Asset[]}` or 404; never starts Daytona.
Public asset URLs use Supabase public published bucket content-hash paths.

## Durable boundary

The standalone API verifies an opaque server-side GitHub session and injects its owner ID into service-role RPC calls. Each RPC checks explicit membership. The browser never supplies the actor ID or privileged storage credentials.

`map_studio_*` tables store projects, canonical source projections, memberships, drafts, leases, versions, assets, idempotency records and session state. Source re-import is an administrative operation. Private asset URLs are scoped API routes; published assets are immutable content-hashed WebP files.

The optional `/api/public/map-studio/{key}` endpoint is disabled by default. Production public pages should use `integrations/public-layers.ts` and the external `map_studio_delivery_manifest` projection, gated by a per-map database flag, to avoid a Daytona dependency.

PostgREST table/composite RPCs return row arrays even for one result. The storage adapter normalizes the single-asset read/register functions; list functions retain arrays. See [PostgREST resource representation](https://postgrest.org/en/latest/references/api/resource_representation.html) and [RPC return shapes](https://postgrest.org/en/v12/references/api/functions.html).
