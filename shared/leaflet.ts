import { validateCanonicalBusiness, validateLayerDocument, validateStudioAsset, type CanonicalBusiness, type LayerDocument, type StudioAsset, type StudioLayer, type Coordinate, type StudioTheme } from './contracts';

export interface StudioLayerMount {
  update(input: { document: LayerDocument; businesses: readonly CanonicalBusiness[]; assets: readonly StudioAsset[]; editable?: boolean }): void;
  dispose(): void;
}
export interface StudioMountOptions {
  L: any; map: any; document: LayerDocument; businesses: readonly CanonicalBusiness[]; assets: readonly StudioAsset[];
  onSelect?: (layer: StudioLayer, business?: CanonicalBusiness) => void;
  onMove?: (layer: StudioLayer, position: Coordinate) => void;
  editable?: boolean;
}

/** The only asset origins accepted by Studio artwork and business logos. */
export function safeStudioAssetUrl(value: string, origin = typeof window === 'undefined' ? 'http://localhost' : window.location.origin): string {
  const base = new URL(origin);
  const url = new URL(value, base);
  const decodedPath = (() => { try { return decodeURIComponent(url.pathname); } catch { return ''; } })();
  if (!decodedPath || decodedPath.split('/').some((part) => part === '..' || part === '.')) throw new Error('Unapproved Map Studio asset URL');
  const sameOrigin = url.origin === base.origin && (url.pathname.startsWith('/api/bff/map-studio/') || url.pathname.startsWith('/publicassets/'));
  const supabasePublic = url.protocol === 'https:' && /^[a-z0-9-]+\.supabase\.co$/i.test(url.hostname) && /^\/storage\/v1\/(object|render)\/public\//.test(url.pathname);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.hash || (!sameOrigin && !supabasePublic)) throw new Error('Unapproved Map Studio asset URL');
  return url.href;
}

export const STUDIO_THEME_STYLES: Record<StudioTheme, Readonly<Record<string, string>>> = Object.freeze({
  original: Object.freeze({ '--studio-map-canvas': '#f8f4f0', '--studio-map-ink': '#292b27', '--studio-map-accent': '#94370d' }),
  paper: Object.freeze({ '--studio-map-canvas': '#f1eadf', '--studio-map-ink': '#453a30', '--studio-map-accent': '#8d5d36' }),
  sage: Object.freeze({ '--studio-map-canvas': '#edf1e6', '--studio-map-ink': '#294e39', '--studio-map-accent': '#527345' }),
});

/** Approved display palettes preserve the basemap's own style and labels. */
export function applyStudioTheme(map: any, theme: StudioTheme): void {
  const container = map?.getContainer?.();
  if (container) {
    container.dataset.studioTheme = theme;
    for (const [key, value] of Object.entries(STUDIO_THEME_STYLES[theme])) container.style.setProperty(key, value);
  }
  const pane = map?.getPane?.('tilePane');
  if (pane) pane.style.filter = theme === 'paper' ? 'sepia(.25) saturate(.8)' : theme === 'sage' ? 'sepia(.12) hue-rotate(20deg) saturate(.75)' : '';
}

const latLng = (position: Coordinate): [number, number] => [position[1], position[0]];
const isInZoom = (layer: StudioLayer, zoom: number): boolean => layer.visible && zoom >= layer.minZoom && zoom <= layer.maxZoom;
const textElement = (doc: Document, text: string, className: string): HTMLElement => {
  const element = doc.createElement('span'); element.className = className; element.textContent = text; return element;
};

export function mountStudioLayers(options: StudioMountOptions): StudioLayerMount {
  const L = options.L, map = options.map;
  let current = validateLayerDocument(options.document);
  let businesses = [...options.businesses];
  let assets = [...options.assets];
  let editable = options.editable === true;
  let disposed = false;
  const records = new Map<string, any>();
  const businessById = new Map<string, CanonicalBusiness>();
  const assetById = new Map<string, StudioAsset>();
  const paneNames = new Set<string>();
  const doc: Document | undefined = map?.getContainer?.()?.ownerDocument || (typeof document !== 'undefined' ? document : undefined);

  const paneFor = (layer: StudioLayer): string => `studioLayerPane-${Math.max(0, current.layers.findIndex(item => item.id === layer.id))}`;
  const ensurePanes = () => {
    if (!map?.createPane) return;
    for (const [index] of current.layers.entries()) {
      const name = `studioLayerPane-${index}`;
      const pane = map.getPane?.(name) || map.createPane(name);
      // Equal integer z-indices paint in DOM order. Index-named panes are
      // created in document order, below Leaflet tooltips/popups/controls.
      // Fractional z-indices are invalid CSS and would drop panes behind tiles.
      if (pane) pane.style.zIndex = '610';
      paneNames.add(name);
    }
  };
  const removePane = (name: string) => {
    if (map.removePane) map.removePane(name);
    else { map.getPane?.(name)?.remove?.(); const panes = map.getPanes?.(); if (panes) delete panes[name]; }
  };
  const removeUnusedPanes = () => {
    const active = new Set(current.layers.map((_, index) => `studioLayerPane-${index}`));
    for (const name of [...paneNames]) {
      if (active.has(name)) continue;
      removePane(name);
      paneNames.delete(name);
    }
  };
  const remove = (item: any) => { if (!item) return; item.off?.(); item.remove?.(); map.removeLayer?.(item); };
  const updateVisibility = () => {
    const zoom = Number(map.getZoom?.() ?? 0);
    current.layers.forEach(layer => {
      const item = records.get(layer.id); if (!item) return;
      const visible = isInZoom(layer, zoom);
      if (visible) { if (item._studioOnMap !== true) { item.addTo?.(map); item._studioOnMap = true; } }
      else if (item._studioOnMap !== false) { item.remove?.(); item._studioOnMap = false; }
      const element = item.getElement?.(); if (element) element.style.opacity = String(layer.opacity);
      item.setStyle?.({ opacity: visible ? layer.opacity : 0, fillOpacity: visible ? layer.opacity * .22 : 0 });
    });
  };
  const installDrag = (item: any, layer: StudioLayer, locked: boolean) => {
    if (!editable || locked || !item?.on) return;
    item.options = { ...(item.options || {}), draggable: true };
    item.on('dragend', () => {
      const point = item.getLatLng?.(); if (!point) return;
      options.onMove?.(layer, [point.lng, point.lat]);
    });
  };
  const markerIcon = (layer: StudioLayer, asset?: StudioAsset, business?: CanonicalBusiness) => {
    if (!L?.divIcon) return undefined;
    const icon = L.divIcon({ className: `studio-marker studio-marker--${layer.kind}`, html: '', iconSize: layer.kind === 'artwork' ? [layer.width, layer.height] : [44, 44], iconAnchor: layer.kind === 'artwork' ? [layer.width / 2, layer.height / 2] : [22, 22] });
    // Leaflet's icon API receives an empty HTML string. Text and images are appended
    // through DOM APIs after add, preventing document labels from becoming markup.
    (icon as any).__studioMount = (element: HTMLElement) => {
      element.replaceChildren();
      if (asset && layer.kind === 'artwork') {
        const image = element.ownerDocument.createElement('img'); image.alt = asset.altText; image.width = layer.width; image.height = layer.height; image.style.width = "100%"; image.style.height = "100%"; image.style.objectFit = "contain"; image.style.transform = `rotate(${layer.rotation}deg)`;
        try { image.src = safeStudioAssetUrl(asset.url, element.ownerDocument.defaultView?.location.origin); } catch { image.remove(); }
        element.append(image);
      } else if (layer.kind === 'annotation') element.append(textElement(element.ownerDocument, layer.text, 'studio-annotation-label'));
      else if (business) {
        element.setAttribute('aria-label', business.name); element.setAttribute('role', 'button');
        if (asset) { try { const image = element.ownerDocument.createElement('img'); image.alt = ''; image.src = safeStudioAssetUrl(asset.url, element.ownerDocument.defaultView?.location.origin); element.append(image); } catch { /* safe fallback is text only */ } }
        if (!element.querySelector('img')) element.append(textElement(element.ownerDocument, business.name.slice(0, 2).toUpperCase(), 'studio-business-fallback'));
      }
      element.style.opacity = String(layer.opacity);
      element.style.pointerEvents = editable || layer.kind === 'business' ? 'auto' : 'none';
      if (layer.kind === 'business') {
        element.dataset.highlight = layer.highlight;
        element.title = `${business!.name}${business!.location?.precisionNote ? ` — ${business!.location.precisionNote}` : ''}`;
        if (layer.highlight !== 'none') element.style.outline = layer.highlight === 'ring' ? '3px solid #94370d' : '3px solid #527345';
      }
    };
    return icon;
  };
  const make = (layer: StudioLayer): any => {
    const business = layer.kind === 'business' ? businessById.get(layer.businessId) : undefined;
    if (layer.kind === 'business' && (!business?.location || !Number.isFinite(business.location.lat) || !Number.isFinite(business.location.lng) || business.location.lat < -90 || business.location.lat > 90 || business.location.lng < -180 || business.location.lng > 180)) return undefined;
    const asset = 'assetId' in layer && layer.assetId ? assetById.get(layer.assetId) : undefined;
    if ('assetId' in layer && layer.assetId && (!asset || asset.state !== 'ready')) return undefined;
    const position: Coordinate = layer.kind === 'geometry' ? ([0, 0] as Coordinate) : layer.kind === 'business' ? [business!.location!.lng, business!.location!.lat] : layer.position;
    const pane = paneFor(layer);
    let item: any;
    if (layer.kind === 'geometry') {
      const geometry = layer.geometry;
      if (geometry.type === 'Point') item = L.circleMarker?.(latLng(geometry.coordinates), { pane, interactive: editable, opacity: layer.opacity, fillOpacity: layer.opacity * .22 }) || L.marker(latLng(geometry.coordinates), { pane });
      else if (geometry.type === 'LineString') item = L.polyline?.(geometry.coordinates.map(latLng), { pane, interactive: editable, opacity: layer.opacity }) || L.layerGroup();
      else item = L.polygon?.(geometry.coordinates.map(ring => ring.map(latLng)), { pane, interactive: editable, opacity: layer.opacity, fillOpacity: layer.opacity * .22 }) || L.layerGroup();
    } else {
      item = L.marker(latLng(position), { pane, interactive: editable || layer.kind === 'business', keyboard: editable || layer.kind === 'business', draggable: editable && layer.kind !== 'business', icon: markerIcon(layer, asset, business), title: '' });
      item.on?.('add', () => { const element = item.getElement?.(); const icon = item.getIcon?.(); if (element && icon?.__studioMount) icon.__studioMount(element); });
      item.on?.('click', () => options.onSelect?.(layer, business));
      installDrag(item, layer, layer.kind === 'business');
    }
    if (layer.kind === 'geometry') item.on?.('click', () => options.onSelect?.(layer));
    item.options = { ...(item.options || {}), pane, studioLayerId: layer.id };
    item.addTo?.(map); item._studioOnMap = true;
    return item;
  };
  const rebuild = () => {
    records.forEach(remove); records.clear(); removeUnusedPanes(); ensurePanes(); applyStudioTheme(map, current.theme);
    current.layers.forEach(layer => { const item = make(layer); if (item) records.set(layer.id, item); });
    updateVisibility();
  };
  const zoomHandler = () => updateVisibility();
  map?.on?.('zoomend', zoomHandler);
  businesses.forEach(item => {
    try { const business = validateCanonicalBusiness(item); if (!businessById.has(business.id)) businessById.set(business.id, business); } catch { /* malformed source rows cannot become markers */ }
  });
  assets.forEach(item => {
    try { const asset = validateStudioAsset(item); if (!assetById.has(asset.id)) assetById.set(asset.id, asset); } catch { /* malformed assets are not renderable */ }
  });
  rebuild();
  return {
    update(input) {
      if (disposed) return;
      current = validateLayerDocument(input.document); businesses = [...input.businesses]; assets = [...input.assets]; editable = input.editable === true;
      businessById.clear(); businesses.forEach(item => { try { const business = validateCanonicalBusiness(item); if (!businessById.has(business.id)) businessById.set(business.id, business); } catch { /* malformed source rows cannot become markers */ } }); assetById.clear(); assets.forEach(item => { try { const asset = validateStudioAsset(item); if (!assetById.has(asset.id)) assetById.set(asset.id, asset); } catch { /* malformed assets are not renderable */ } }); rebuild();
    },
    dispose() { if (disposed) return; disposed = true; map?.off?.('zoomend', zoomHandler); records.forEach(remove); records.clear(); for (const name of paneNames) removePane(name); applyStudioTheme(map, 'original'); paneNames.clear(); },
  };
}
