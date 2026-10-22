/** Shared, host-neutral Map Studio document and public view contracts. */

export type StudioTheme = 'original' | 'paper' | 'sage';
export type Coordinate = readonly [number, number];

export interface StudioCommonLayer {
  id: string;
  kind: StudioLayerKind;
  name: string;
  visible: boolean;
  opacity: number;
  minZoom: number;
  maxZoom: number;
  category?: string;
}
export type StudioLayerKind = 'artwork' | 'annotation' | 'geometry' | 'business';
export interface StudioArtworkLayer extends StudioCommonLayer {
  kind: 'artwork'; assetId: string; position: Coordinate; width: number; height: number; rotation: number;
}
export interface StudioAnnotationLayer extends StudioCommonLayer {
  kind: 'annotation'; text: string; position: Coordinate;
}
export type StudioGeometry =
  | { type: 'Point'; coordinates: Coordinate }
  | { type: 'LineString'; coordinates: readonly Coordinate[] }
  | { type: 'Polygon'; coordinates: readonly (readonly Coordinate[])[] };
export interface StudioGeometryLayer extends StudioCommonLayer {
  kind: 'geometry'; geometry: StudioGeometry;
}
export interface StudioBusinessLayer extends StudioCommonLayer {
  kind: 'business'; businessId: string; assetId?: string; highlight: 'none' | 'accent' | 'ring';
}
export type StudioLayer = StudioArtworkLayer | StudioAnnotationLayer | StudioGeometryLayer | StudioBusinessLayer;
export interface LayerDocument { schemaVersion: 1; mapKey: string; theme: StudioTheme; layers: readonly StudioLayer[]; }

export interface CanonicalBusiness {
  id: string; name: string; category?: string;
  location?: { lat: number; lng: number; precisionNote?: string };
  logoUrl?: string;
}
export interface StudioAsset {
  id: string; name: string; altText: string; rights: string; url: string;
  width: number; height: number; state: 'ready';
}
export interface StudioProject {
  mapKey: string; title: string; city: string; publicPath: string;
  center: Coordinate; sourceRevision: string;
}

// Limits keep technically valid but intentionally expensive documents from
// consuming unbounded browser memory or Canvas/Leaflet paint time.
export const STUDIO_LIMITS = Object.freeze({
  mapKey: 100,
  identifier: 128,
  label: 200,
  category: 100,
  annotation: 2000,
  artworkDimension: 4096,
  geometryCoordinates: 5000,
  polygonRings: 64,
  polygonRingCoordinates: 2000,
});

const fail = (path: string, message: string): never => { throw new Error(`Invalid Map Studio document at ${path}: ${message}`); };
const object = (value: unknown, path: string): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return fail(path, 'expected an object');
  return value as Record<string, unknown>;
};
const exact = (value: Record<string, unknown>, allowed: readonly string[], path: string) => {
  const allowedSet = new Set(allowed);
  for (const key of Object.keys(value)) if (!allowedSet.has(key)) fail(`${path}.${key}`, 'unsupported property');
};
const stringValue = (value: unknown, path: string, maxLength: number = STUDIO_LIMITS.label): string => {
  if (typeof value !== 'string' || !value.trim()) return fail(path, 'expected a non-empty string');
  if (value !== value.trim()) return fail(path, 'must not have leading or trailing whitespace');
  if (value.length > maxLength) return fail(path, `must be at most ${maxLength} characters`);
  if ([...value].some((character) => character === '\u0000' || (character < ' ' && character !== '\n' && character !== '\t'))) return fail(path, 'contains a control character');
  return value;
};
const identifier = (value: unknown, path: string, maxLength = STUDIO_LIMITS.identifier): string => {
  const result = stringValue(value, path, maxLength);
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(result)) return fail(path, 'contains unsupported identifier characters');
  return result;
};
const mapKey = (value: unknown, path: string): string => {
  const result = stringValue(value, path, STUDIO_LIMITS.mapKey);
  if (!/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(result)) return fail(path, 'must be a lowercase map key');
  return result;
};
const finite = (value: unknown, path: string) => { if (typeof value !== 'number' || !Number.isFinite(value)) return fail(path, 'expected a finite number'); return value; };
const bool = (value: unknown, path: string) => { if (typeof value !== 'boolean') return fail(path, 'expected a boolean'); return value; };
const coordinate = (value: unknown, path: string): Coordinate => {
  if (!Array.isArray(value) || value.length !== 2) return fail(path, 'expected [longitude, latitude]');
  const lng = finite(value[0], `${path}[0]`), lat = finite(value[1], `${path}[1]`);
  if (lng < -180 || lng > 180 || lat < -90 || lat > 90) return fail(path, 'coordinate is out of range');
  return [lng, lat];
};
const geometry = (value: unknown, path: string): StudioGeometry => {
  const item = object(value, path); exact(item, ['type', 'coordinates'], path);
  if (item.type === 'Point') return { type: 'Point', coordinates: coordinate(item.coordinates, `${path}.coordinates`) };
  if (item.type === 'LineString') {
    if (!Array.isArray(item.coordinates) || item.coordinates.length < 2) return fail(`${path}.coordinates`, 'LineString needs two coordinates');
    if (item.coordinates.length > STUDIO_LIMITS.geometryCoordinates) return fail(`${path}.coordinates`, 'LineString is too complex');
    return { type: 'LineString', coordinates: item.coordinates.map((v, i) => coordinate(v, `${path}.coordinates[${i}]`)) };
  }
  if (item.type === 'Polygon') {
    if (!Array.isArray(item.coordinates) || item.coordinates.length < 1) return fail(`${path}.coordinates`, 'Polygon needs rings');
    if (item.coordinates.length > STUDIO_LIMITS.polygonRings) return fail(`${path}.coordinates`, 'Polygon has too many rings');
    const total = item.coordinates.reduce((sum, ring) => sum + (Array.isArray(ring) ? ring.length : 0), 0);
    if (total > STUDIO_LIMITS.geometryCoordinates) return fail(`${path}.coordinates`, 'Polygon is too complex');
    return { type: 'Polygon', coordinates: item.coordinates.map((ring, i) => {
      if (!Array.isArray(ring) || ring.length < 4) return fail(`${path}.coordinates[${i}]`, 'ring needs four coordinates');
      if (ring.length > STUDIO_LIMITS.polygonRingCoordinates) return fail(`${path}.coordinates[${i}]`, 'ring is too complex');
      const result = ring.map((v, j) => coordinate(v, `${path}.coordinates[${i}][${j}]`));
      if (result[0][0] !== result[result.length - 1][0] || result[0][1] !== result[result.length - 1][1]) return fail(`${path}.coordinates[${i}]`, 'ring must be closed');
      return result;
    }) };
  }
  return fail(`${path}.type`, 'unsupported geometry type');
};

export function validateLayerDocument(input: unknown): LayerDocument {
  const value = object(input, 'document'); exact(value, ['schemaVersion', 'mapKey', 'theme', 'layers'], 'document');
  if (value.schemaVersion !== 1) fail('document.schemaVersion', 'must be 1');
  const documentMapKey = mapKey(value.mapKey, 'document.mapKey');
  if (value.theme !== 'original' && value.theme !== 'paper' && value.theme !== 'sage') fail('document.theme', 'unsupported theme');
  if (!Array.isArray(value.layers)) fail('document.layers', 'expected an array');
  const layerValues = value.layers as unknown[];
  const layerIds = new Set<string>();
  const layers = layerValues.map((raw: unknown, index: number) => {
    const path = `document.layers[${index}]`, item = object(raw, path);
    const kind = item.kind;
    const common = ['id', 'kind', 'name', 'visible', 'opacity', 'minZoom', 'maxZoom', 'category'];
    if (kind === 'artwork') exact(item, [...common, 'assetId', 'position', 'width', 'height', 'rotation'], path);
    else if (kind === 'annotation') exact(item, [...common, 'text', 'position'], path);
    else if (kind === 'geometry') exact(item, [...common, 'geometry'], path);
    else if (kind === 'business') exact(item, [...common, 'businessId', 'assetId', 'highlight'], path);
    else fail(`${path}.kind`, 'unsupported layer kind');
    const id = identifier(item.id, `${path}.id`); if (layerIds.has(id)) fail(`${path}.id`, 'duplicate layer id'); layerIds.add(id);
    const base = { id, kind: kind as StudioLayerKind, name: stringValue(item.name, `${path}.name`), visible: bool(item.visible, `${path}.visible`), opacity: finite(item.opacity, `${path}.opacity`), minZoom: finite(item.minZoom, `${path}.minZoom`), maxZoom: finite(item.maxZoom, `${path}.maxZoom`), ...(item.category === undefined ? {} : { category: stringValue(item.category, `${path}.category`, STUDIO_LIMITS.category) }) };
    if (base.opacity < 0 || base.opacity > 1) fail(`${path}.opacity`, 'must be between 0 and 1');
    if (base.minZoom < 0 || base.maxZoom > 24 || base.minZoom > base.maxZoom) fail(path, 'invalid zoom range');
    if (kind === 'artwork') {
      const width = finite(item.width, `${path}.width`), height = finite(item.height, `${path}.height`), rotation = finite(item.rotation, `${path}.rotation`);
      if (width <= 0 || height <= 0 || width > STUDIO_LIMITS.artworkDimension || height > STUDIO_LIMITS.artworkDimension) fail(path, 'artwork dimensions are outside bounds');
      if (rotation < -3600 || rotation > 3600) fail(`${path}.rotation`, 'rotation is outside bounds');
      return { ...base, kind: 'artwork', assetId: identifier(item.assetId, `${path}.assetId`), position: coordinate(item.position, `${path}.position`), width, height, rotation } as StudioArtworkLayer;
    }
    if (kind === 'annotation') return { ...base, kind: 'annotation', text: stringValue(item.text, `${path}.text`, STUDIO_LIMITS.annotation), position: coordinate(item.position, `${path}.position`) } as StudioAnnotationLayer;
    if (kind === 'geometry') return { ...base, kind: 'geometry', geometry: geometry(item.geometry, `${path}.geometry`) } as StudioGeometryLayer;
    const businessId = identifier(item.businessId, `${path}.businessId`);
    const assetId = item.assetId === undefined ? undefined : identifier(item.assetId, `${path}.assetId`);
    if (item.highlight !== 'none' && item.highlight !== 'accent' && item.highlight !== 'ring') fail(`${path}.highlight`, 'unsupported highlight');
    return { ...base, kind: 'business', businessId, ...(assetId === undefined ? {} : { assetId }), highlight: item.highlight } as StudioBusinessLayer;
  });
  return { schemaVersion: 1, mapKey: documentMapKey, theme: value.theme as StudioTheme, layers };
}

/** Validate canonical source data before it can be used as a business marker. */
export function validateCanonicalBusiness(input: unknown, path = 'business'): CanonicalBusiness {
  const value = object(input, path); exact(value, ['id', 'name', 'category', 'location', 'logoUrl'], path);
  const location = value.location === undefined ? undefined : (() => {
    const point = object(value.location, `${path}.location`); exact(point, ['lat', 'lng', 'precisionNote'], `${path}.location`);
    const lat = finite(point.lat, `${path}.location.lat`), lng = finite(point.lng, `${path}.location.lng`);
    if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return fail(`${path}.location`, 'coordinate is out of range');
    return { lat, lng, ...(point.precisionNote === undefined ? {} : { precisionNote: stringValue(point.precisionNote, `${path}.location.precisionNote`, STUDIO_LIMITS.label) }) };
  })();
  return {
    id: identifier(value.id, `${path}.id`), name: stringValue(value.name, `${path}.name`),
    ...(value.category === undefined ? {} : { category: stringValue(value.category, `${path}.category`, STUDIO_LIMITS.category) }),
    ...(location === undefined ? {} : { location }),
    ...(value.logoUrl === undefined ? {} : { logoUrl: stringValue(value.logoUrl, `${path}.logoUrl`, 2048) }),
  };
}

/** Validate the renderer-facing asset metadata; URL policy is applied at use time. */
export function validateStudioAsset(input: unknown, path = 'asset'): StudioAsset {
  const value = object(input, path); exact(value, ['id', 'name', 'altText', 'rights', 'url', 'width', 'height', 'state'], path);
  const width = finite(value.width, `${path}.width`), height = finite(value.height, `${path}.height`);
  if (width <= 0 || height <= 0 || width > STUDIO_LIMITS.artworkDimension || height > STUDIO_LIMITS.artworkDimension) fail(path, 'asset dimensions are outside bounds');
  if (value.state !== 'ready') fail(`${path}.state`, 'asset is not ready');
  return { id: identifier(value.id, `${path}.id`), name: stringValue(value.name, `${path}.name`), altText: stringValue(value.altText, `${path}.altText`, STUDIO_LIMITS.annotation), rights: stringValue(value.rights, `${path}.rights`, STUDIO_LIMITS.annotation), url: stringValue(value.url, `${path}.url`, 4096), width, height, state: 'ready' };
}

export function emptyLayerDocument(mapKeyValue: string): LayerDocument {
  return { schemaVersion: 1, mapKey: mapKey(mapKeyValue, 'mapKey'), theme: 'original', layers: [] };
}
