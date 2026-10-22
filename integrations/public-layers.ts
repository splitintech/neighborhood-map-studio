/** Attach after the existing public map's consent gate. No Daytona dependency. */
import { mountStudioLayers, type StudioLayerMount } from '../shared/leaflet';
import { validateLayerDocument, validateStudioAsset, type CanonicalBusiness, type StudioAsset } from '../shared/contracts';

export interface PublishedLayerMount extends StudioLayerMount {
  updateBusinesses(businesses: readonly CanonicalBusiness[]): void;
}

export interface PublicLayerFetcher {
  (input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
}

/** Pilot projections are tied to exact editorial guide identities. */
export function resolvePublicPilotMapKey(options: { city?: string; pathname?: string; explicitMapKey?: string }): string | undefined {
  const city = options.city === 'sanFrancisco' ? 'san-francisco' : options.city;
  const allowed: Record<string, string> = { 'san-francisco-mission': 'san-francisco', 'boston-back-bay': 'boston' };
  const explicit = options.explicitMapKey?.trim();
  if (explicit && allowed[explicit] === city) return explicit;
  const path = (options.pathname || '').replace(/\/+$/, '');
  const match = path.match(/^\/blog\/guides\/([^/]+)\/places$/);
  const routeKey = match?.[1];
  return routeKey && allowed[routeKey] === city ? routeKey : undefined;
}

const publicOrigin = (value: string): URL => {
  const origin = new URL(value);
  if (origin.protocol !== 'https:' || !/^[a-z0-9-]+\.supabase\.co$/i.test(origin.hostname)
    || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) throw new Error('Invalid public Map Studio origin');
  return origin;
};

const requestSignal = (): AbortSignal | undefined => typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function' ? AbortSignal.timeout(5000) : undefined;

export async function attachPublishedLayers(options: {
  mapKey: string; enabled: boolean; supabaseOrigin: string; publicAnonKey: string;
  L: any; map: any; businesses: readonly CanonicalBusiness[];
  setBusinessSuppressed: (businessId: string, suppressed: boolean) => void;
  selectBusiness: (businessId: string) => void;
  fetcher?: PublicLayerFetcher;
}): Promise<PublishedLayerMount | undefined> {
  if (!options.enabled) return;
  try {
    const origin = publicOrigin(options.supabaseOrigin);
    const anonKey = options.publicAnonKey.trim();
    if (!anonKey) return;
    const response = await (options.fetcher || fetch)(new URL('/rest/v1/rpc/map_studio_delivery_manifest', origin), {
      method: 'POST', credentials: 'omit', signal: requestSignal(),
      headers: { 'Content-Type': 'application/json', apikey: anonKey,
        Authorization: `Bearer ${anonKey}` },
      body: JSON.stringify({ p_map_key: options.mapKey }),
    });
    if (!response.ok) return;
    const manifest = await response.json();
    if (!manifest || typeof manifest.versionId !== 'string' || !Array.isArray(manifest.assets)) return;
    const document = validateLayerDocument(manifest.document);
    if (document.mapKey !== options.mapKey) return;
    const assets: StudioAsset[] = manifest.assets.map((asset: Record<string, unknown>) => {
      if (typeof asset.publicPath !== 'string' || !/^[a-f0-9]{64}\.webp$/.test(asset.publicPath)) throw new Error('Invalid asset');
      if (typeof asset.id !== 'string' || typeof asset.name !== 'string' || typeof asset.altText !== 'string' ||
          typeof asset.rights !== 'string' || typeof asset.width !== 'number' || typeof asset.height !== 'number' || asset.state !== 'ready') throw new Error('Invalid asset');
      return validateStudioAsset({ id: asset.id, name: asset.name, altText: asset.altText, rights: asset.rights,
        width: asset.width, height: asset.height, state: 'ready',
        url: new URL(`/storage/v1/object/public/map-studio-published/${asset.publicPath}`, origin).href });
    });
    let currentDocument = document;
    let currentAssets = [...assets];
    let businesses = [...options.businesses];
    const mount = mountStudioLayers({ L: options.L, map: options.map, document: currentDocument, assets: currentAssets,
      businesses, onSelect: (layer) => {
        if (layer.kind === 'business') options.selectBusiness(layer.businessId);
      } });
    const suppressed = new Set<string>();
    const applySuppression = () => {
      const canonical = new Set(businesses.filter(b => b.location).map(b => b.id));
      // A published business layer owns the canonical marker's visibility. A
      // hidden or out-of-zoom overlay must therefore keep the base marker
      // suppressed instead of revealing a duplicate beneath it.
      const next = new Set(currentDocument.layers.flatMap(layer =>
        layer.kind === 'business' && canonical.has(layer.businessId) ? [layer.businessId] : []));
      const previous = new Set(suppressed);
      suppressed.clear(); next.forEach(id => suppressed.add(id));
      for (const id of previous) if (!next.has(id)) options.setBusinessSuppressed(id, false);
      for (const id of next) if (!previous.has(id)) options.setBusinessSuppressed(id, true);
    };
    applySuppression();
    return {
      update: (input) => {
        currentDocument = validateLayerDocument(input.document);
        currentAssets = [...input.assets];
        businesses = [...input.businesses];
        mount.update({ ...input, document: currentDocument, assets: currentAssets, businesses });
        applySuppression();
      },
      updateBusinesses: (next) => {
        businesses = [...next];
        mount.update({ document: currentDocument, businesses, assets: currentAssets });
        applySuppression();
      },
      dispose: () => {
        mount.dispose();
        for (const id of suppressed) options.setBusinessSuppressed(id, false);
      },
    };
  } catch {
    // Keep existing cards, markers, search, attribution and map/list selection.
    return undefined;
  }
}
