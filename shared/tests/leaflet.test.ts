import assert from 'node:assert/strict';
import test from 'node:test';
import { applyStudioTheme, mountStudioLayers, safeStudioAssetUrl } from '../leaflet';

class Element {
  style = { opacity: '', setProperty: (_key: string, _value: string) => undefined };
  dataset: Record<string, string> = {};
  children: Element[] = [];
  ownerDocument = { createElement: () => new Element(), defaultView: { location: { origin: 'https://studio.example' } } };
  append(...children: Element[]) { this.children.push(...children); }
  replaceChildren(...children: Element[]) { this.children = children; }
  setAttribute(_name: string, _value: string) { /* DOM shape for marker tests */ }
  querySelector(_selector: string) { return this.children.find((child) => child.tagName === 'img') ?? null; }
  tagName = 'span';
  className = '';
  textContent = '';
  width = 0;
  height = 0;
}

class FakeLayer {
  handlers = new Map<string, () => void>();
  options: Record<string, unknown>;
  _studioOnMap = false;
  element = new Element();
  constructor(public readonly kind: string, public readonly coords: unknown, options: Record<string, unknown> = {}) { this.options = options; }
  on(name: string, handler: () => void) { this.handlers.set(name, handler); return this; }
  off() { this.handlers.clear(); }
  addTo(map: FakeMap) { map.layers.add(this); this._studioOnMap = true; this.handlers.get('add')?.(); return this; }
  remove() { this._studioOnMap = false; return this; }
  getElement() { return this.element; }
  getIcon() { return this.options.icon; }
  getLatLng() { const point = this.coords as [number, number]; return { lat: point[0], lng: point[1] }; }
  setStyle(style: Record<string, unknown>) { this.options = { ...this.options, ...style }; }
}

class FakeMap {
  panes = new Map<string, Element>();
  layers = new Set<FakeLayer>();
  handlers = new Map<string, () => void>();
  zoom = 14;
  container = new Element();
  getContainer() { return this.container; }
  createPane(name: string) { const pane = new Element(); this.panes.set(name, pane); return pane; }
  getPane(name: string) { return this.panes.get(name); }
  removePane(name: string) { this.panes.delete(name); }
  on(name: string, handler: () => void) { this.handlers.set(name, handler); }
  off(name: string) { this.handlers.delete(name); }
  getZoom() { return this.zoom; }
  removeLayer(layer: FakeLayer) { this.layers.delete(layer); }
}

const L = {
  divIcon: (options: Record<string, unknown>) => options,
  marker: (coords: unknown, options: Record<string, unknown>) => new FakeLayer('marker', coords, options),
  circleMarker: (coords: unknown, options: Record<string, unknown>) => new FakeLayer('circle', coords, options),
  polyline: (coords: unknown, options: Record<string, unknown>) => new FakeLayer('line', coords, options),
  polygon: (coords: unknown, options: Record<string, unknown>) => new FakeLayer('polygon', coords, options),
  layerGroup: () => new FakeLayer('group', []),
};

const documentValue = {
  schemaVersion: 1 as const, mapKey: 'san-francisco-mission', theme: 'original' as const,
  layers: [{ id: 'business-layer', kind: 'business' as const, name: 'Cafe', visible: true, opacity: 1, minZoom: 0, maxZoom: 24, businessId: 'business-1', highlight: 'none' as const }],
};

test('asset URL policy rejects traversal and untrusted origins', () => {
  assert.equal(safeStudioAssetUrl('/publicassets/cafe.png', 'https://studio.example'), 'https://studio.example/publicassets/cafe.png');
  assert.throws(() => safeStudioAssetUrl('/publicassets/%2e%2e/private.png', 'https://studio.example'));
  assert.throws(() => safeStudioAssetUrl('https://evil.example/cafe.png', 'https://studio.example'));
  assert.equal(safeStudioAssetUrl('https://project.supabase.co/storage/v1/object/public/map/cafe.png', 'https://studio.example'), 'https://project.supabase.co/storage/v1/object/public/map/cafe.png');
});

test('renderer uses canonical business location, locks business movement, and cleans panes', () => {
  const map = new FakeMap();
  const selected: string[] = [];
  const mount = mountStudioLayers({ L, map, document: documentValue, businesses: [{ id: 'business-1', name: 'Cafe', location: { lat: 37.75, lng: -122.4 } }], assets: [], editable: true, onSelect: (layer) => selected.push(layer.id) });
  assert.equal(map.panes.size, 1);
  const marker = [...map.layers][0];
  assert.deepEqual(marker.coords, [37.75, -122.4]);
  assert.equal(marker.options.draggable, false);
  marker.handlers.get('click')?.();
  assert.deepEqual(selected, ['business-layer']);
  mount.update({ document: { ...documentValue, layers: [] }, businesses: [], assets: [], editable: true });
  assert.equal(map.panes.size, 0);
  mount.dispose();
});

test('annotation labels stay text nodes when rendered', () => {
  const map = new FakeMap();
  const mount = mountStudioLayers({ L, map, document: { schemaVersion: 1, mapKey: 'san-francisco-mission', theme: 'original', layers: [{ id: 'label-1', kind: 'annotation', name: 'Label', visible: true, opacity: 1, minZoom: 0, maxZoom: 24, text: '<img src=x onerror=alert(1)>', position: [-122.4, 37.75] }] }, businesses: [], assets: [] });
  const marker = [...map.layers][0];
  assert.equal(marker.element.children[0]?.textContent, '<img src=x onerror=alert(1)>');
  assert.equal(marker.element.children[0]?.tagName, 'span');
  mount.dispose();
});

test('ordered panes use integer CSS stacking levels below Leaflet controls', () => {
  const map = new FakeMap();
  const layers = [0, 1, 2].map(index => ({
    ...documentValue.layers[0], id: `business-${index}`,
  }));
  const mount = mountStudioLayers({ L, map, document: { ...documentValue, layers }, businesses: [], assets: [] });
  assert.deepEqual([...map.panes.keys()], ['studioLayerPane-0', 'studioLayerPane-1', 'studioLayerPane-2']);
  for (const pane of map.panes.values()) {
    assert.match(pane.style.zIndex, /^\d+$/);
    assert.ok(Number(pane.style.zIndex) >= 600 && Number(pane.style.zIndex) < 650);
  }
  mount.dispose();
});

test('approved themes preserve canonical basemap styles and reset the tile filter', () => {
  const map = new FakeMap();
  const pane = map.createPane('tilePane');
  applyStudioTheme(map, 'sage');
  assert.match(pane.style.filter, /hue-rotate/);
  applyStudioTheme(map, 'paper');
  assert.match(pane.style.filter, /sepia/);
  applyStudioTheme(map, 'original');
  assert.equal(pane.style.filter, '');
});

test('artwork rotation stays on the image and never replaces Leaflet marker translation', () => {
  const map = new FakeMap();
  const mount = mountStudioLayers({ L, map, editable: true, businesses: [],
    document: { schemaVersion: 1, mapKey: 'san-francisco-mission', theme: 'original', layers: [
      { id: 'artwork-1', kind: 'artwork', name: 'Drawing', visible: true, opacity: 1, minZoom: 0, maxZoom: 24,
        assetId: 'asset-1', position: [-122.4, 37.75], width: 120, height: 60, rotation: 35 },
    ] }, assets: [{ id: 'asset-1', name: 'Drawing', altText: 'Drawing', rights: 'Original',
      url: '/api/bff/map-studio/projects/san-francisco-mission/assets/a/content', width: 240, height: 120, state: 'ready' }],
  });
  const marker = [...map.layers][0];
  assert.deepEqual(marker.coords, [37.75, -122.4]);
  assert.equal(marker.element.style.transform, undefined);
  assert.equal(marker.element.children[0].style.transform, 'rotate(35deg)');
  assert.equal(marker.element.children[0].width, 120);
  assert.equal(marker.element.children[0].height, 60);
  mount.dispose();
});
