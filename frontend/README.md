# Map Studio app

This is the standalone Vite application surface for the Map Studio pilot. It expects the authenticated BFF at `/api/bff/map-studio` and uses cookie credentials plus the existing `X-CSRF-Token` session token for mutations. The app never sends a browser bearer token.

Run from the repository root:

```sh
npm run dev --prefix apps/map-studio
npm run typecheck --prefix apps/map-studio
npm run test --prefix apps/map-studio
npm run build --prefix apps/map-studio
```

The app uses real Leaflet/OpenStreetMap streets in `src/RealMap.tsx`, the shared renderer from `../shared/leaflet.ts`, and `terra-draw-leaflet-adapter` for pointer/touch geometry creation. The canonical backend API paths are centralized in `src/api.ts`; the project and layer type shapes mirror the implementation contract.
