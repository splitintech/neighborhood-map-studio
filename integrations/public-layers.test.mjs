import assert from "node:assert/strict";
import test from "node:test";
import { build } from "../frontend/node_modules/esbuild/lib/main.js";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const directory = await mkdtemp(join(tmpdir(), "map-studio-public-tests-"));
const output = join(directory, "public-layers.mjs");
await build({ entryPoints: ["integrations/public-layers.ts"], bundle: true, platform: "node", format: "esm", outfile: output });
const adapter = await import(`file://${output}`);

const fakeMap = () => ({
  on() {}, off() {}, getZoom: () => 12,
  getContainer: () => ({ dataset: {}, style: { setProperty() {} } }),
  getPane: () => undefined, createPane: () => ({ style: { zIndex: "" } }), removeLayer() {},
});

const fakeLeaflet = {
  marker() {
    const handlers = new Map();
    return {
      on(name, handler) { handlers.set(name, handler); return this; },
      off() {}, remove() {}, addTo() { return this; },
      getElement() { return undefined; },
      getIcon() { return undefined; },
      options: {},
    };
  },
};

const business = { id: "place-1", name: "Place One", location: { lat: 42.35, lng: -71.08 } };
const documentWithBusiness = (visible) => ({ schemaVersion: 1, mapKey: "san-francisco-mission", theme: "original", layers: [{
  id: "place-layer", kind: "business", name: "Place One", visible, opacity: 1, minZoom: 0, maxZoom: 24,
  businessId: "place-1", highlight: "none",
}] });
const manifest = (document) => ({ versionId: "version-1", document, assets: [] });

test("pilot route mapping rejects city-wide and category inheritance", () => {
  assert.equal(adapter.resolvePublicPilotMapKey({ city: "san-francisco", pathname: "/blog/guides/san-francisco-mission/places/" }), "san-francisco-mission");
  assert.equal(adapter.resolvePublicPilotMapKey({ city: "boston", pathname: "/blog/guides/boston-back-bay/places/" }), "boston-back-bay");
  assert.equal(adapter.resolvePublicPilotMapKey({ city: "san-francisco", pathname: "/blog/neighborhood/cafes/san-francisco/" }), undefined);
  assert.equal(adapter.resolvePublicPilotMapKey({ city: "boston", pathname: "/blog/guides/san-francisco-mission/places/" }), undefined);
});

test("adapter requests only the published Supabase projection", async () => {
  const requests = [];
  const mount = await adapter.attachPublishedLayers({
    mapKey: "san-francisco-mission", enabled: true,
    supabaseOrigin: "https://project.supabase.co", publicAnonKey: "anon-key",
    L: {}, map: fakeMap(), businesses: [], setBusinessSuppressed() {}, selectBusiness() {},
    fetcher: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify({ versionId: "version-1", document: { schemaVersion: 1, mapKey: "san-francisco-mission", theme: "original", layers: [] }, assets: [] }), { status: 200 });
    },
  });
  assert.ok(mount);
  assert.equal(requests[0].url, "https://project.supabase.co/rest/v1/rpc/map_studio_delivery_manifest");
  assert.equal(requests[0].init.headers.apikey, "anon-key");
  assert.equal(requests[0].init.credentials, "omit");
  mount.dispose();
});

test("business suppression follows published references through hidden, filtered, and document updates", async () => {
  const changes = [];
  const mount = await adapter.attachPublishedLayers({
    mapKey: "san-francisco-mission", enabled: true,
    supabaseOrigin: "https://project.supabase.co", publicAnonKey: "anon-key",
    L: fakeLeaflet, map: fakeMap(), businesses: [business],
    setBusinessSuppressed: (id, suppressed) => changes.push(`${id}:${suppressed}`), selectBusiness() {},
    fetcher: async () => new Response(JSON.stringify(manifest(documentWithBusiness(true))), { status: 200 }),
  });
  assert.ok(mount);
  assert.deepEqual(changes, ["place-1:true"]);

  // The overlay owns the marker even when its own visibility/zoom rules hide it.
  mount.update({ document: documentWithBusiness(false), businesses: [business], assets: [] });
  assert.deepEqual(changes, ["place-1:true"]);

  // Host filter/area changes remove and then restore the canonical source row.
  mount.updateBusinesses([]);
  assert.deepEqual(changes, ["place-1:true", "place-1:false"]);
  mount.updateBusinesses([business]);
  assert.deepEqual(changes, ["place-1:true", "place-1:false", "place-1:true"]);

  // A later published document update must release suppression when the
  // reference itself disappears, rather than retaining the initial document.
  mount.update({ document: { schemaVersion: 1, mapKey: "san-francisco-mission", theme: "original", layers: [] }, businesses: [business], assets: [] });
  assert.deepEqual(changes, ["place-1:true", "place-1:false", "place-1:true", "place-1:false"]);
  mount.dispose();
});

await rm(directory, { recursive: true, force: true });
