import assert from 'node:assert/strict';
import test from 'node:test';
import { emptyLayerDocument, validateCanonicalBusiness, validateLayerDocument, validateStudioAsset } from '../contracts';

const base = (layer: Record<string, unknown>) => ({ schemaVersion: 1, mapKey: 'san-francisco-mission', theme: 'original', layers: [layer] });
const annotation = (extra: Record<string, unknown> = {}) => ({ id: 'label-1', kind: 'annotation', name: 'Mission', visible: true, opacity: 1, minZoom: 0, maxZoom: 24, text: 'Mission', position: [-122.4, 37.75], ...extra });

test('strict documents reject unsafe identifiers, labels, and duplicate layer ids', () => {
  assert.throws(() => validateLayerDocument(base(annotation({ id: '../escape' }))));
  // Markup-like labels remain display text; the renderer inserts them with
  // textContent, while the document boundary still enforces a hard length.
  assert.equal((validateLayerDocument(base(annotation({ text: '<script>alert(1)</script>' }))).layers[0] as { text: string }).text, '<script>alert(1)</script>');
  assert.throws(() => validateLayerDocument(base(annotation({ text: 'x'.repeat(2001) }))));
  assert.throws(() => validateLayerDocument({ ...base(annotation()), layers: [annotation(), annotation({ name: 'Other' })] }));
});

test('geometry bounds reject excessive coordinate complexity and open rings', () => {
  const line = Array.from({ length: 5001 }, (_, index) => [-122.4 + index / 1e6, 37.75] as const);
  assert.throws(() => validateLayerDocument(base({ id: 'line-1', kind: 'geometry', name: 'Line', visible: true, opacity: 1, minZoom: 0, maxZoom: 24, geometry: { type: 'LineString', coordinates: line } })));
  assert.throws(() => validateLayerDocument(base({ id: 'polygon-1', kind: 'geometry', name: 'Polygon', visible: true, opacity: 1, minZoom: 0, maxZoom: 24, geometry: { type: 'Polygon', coordinates: [[[-122.4, 37.75], [-122.3, 37.75], [-122.3, 37.8], [-122.4, 37.8]]] } })));
});

test('canonical business data keeps source location separate from layer data', () => {
  const business = validateCanonicalBusiness({ id: 'business-1', name: 'Cafe', location: { lat: 37.75, lng: -122.4, precisionNote: 'block' } });
  assert.deepEqual(business.location, { lat: 37.75, lng: -122.4, precisionNote: 'block' });
  assert.throws(() => validateCanonicalBusiness({ id: 'business-1', name: 'Cafe', location: { lat: 3775, lng: -122.4 } }));
  assert.throws(() => validateCanonicalBusiness({ id: 'business-1', name: 'Cafe', location: { lat: 37.75, lng: -122.4, contributorLocation: [1, 2] } }));
});

test('asset IDs and dimensions are validated before URL policy is applied', () => {
  assert.throws(() => validateStudioAsset({ id: '../private', name: 'Photo', altText: 'Photo', rights: 'owned', url: '/publicassets/photo.jpg', width: 100, height: 100, state: 'ready' }));
  assert.throws(() => validateStudioAsset({ id: 'asset-1', name: 'Photo', altText: 'Photo', rights: 'owned', url: '/publicassets/photo.jpg', width: 5000, height: 100, state: 'ready' }));
  assert.equal(validateStudioAsset({ id: 'asset-1', name: 'Photo', altText: 'Photo', rights: 'owned', url: '/publicassets/photo.jpg', width: 100, height: 100, state: 'ready' }).id, 'asset-1');
});

test('empty documents validate their map key', () => {
  assert.deepEqual(emptyLayerDocument('boston-back-bay'), { schemaVersion: 1, mapKey: 'boston-back-bay', theme: 'original', layers: [] });
  assert.throws(() => emptyLayerDocument('Boston Back Bay'));
});
