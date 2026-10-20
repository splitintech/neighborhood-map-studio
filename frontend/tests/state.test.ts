import assert from "node:assert/strict";
import test from "node:test";
import { duplicateLayer, moveLayer, removeLayer, updateLayer } from "../src/state";
import { emptyLayerDocument, validateLayerDocument, type LayerDocument } from "../src/types";
if (!(globalThis as { crypto?: Crypto }).crypto) Object.defineProperty(globalThis, "crypto", { value: { randomUUID: () => "generated-test-id" } });

const base = (): LayerDocument => ({ ...emptyLayerDocument("san-francisco-mission"), layers: [
  { id: "a", kind: "annotation", name: "One", text: "One", position: [-122.42, 37.77], visible: true, opacity: 1, minZoom: 0, maxZoom: 24 },
  { id: "b", kind: "geometry", name: "Two", geometry: { type: "Point", coordinates: [-122.41, 37.78] }, visible: true, opacity: .8, minZoom: 4, maxZoom: 18 },
] });

test("layer edits preserve document shape and toggle only the targeted layer", () => {
  const next = updateLayer(base(), "a", { visible: false, opacity: .5 });
  assert.equal(next.layers[0].visible, false); assert.equal(next.layers[0].opacity, .5); assert.equal(next.layers[1].visible, true);
});
test("drawing order moves up and down without losing layers", () => {
  const next = moveLayer(base(), "a", "up"); assert.deepEqual(next.layers.map((layer) => layer.id), ["b", "a"]);
  assert.deepEqual(moveLayer(next, "a", "down").layers.map((layer) => layer.id), ["a", "b"]);
});
test("duplicate inserts a distinct layer directly after its source", () => {
  const next = duplicateLayer(base(), "a"); assert.equal(next.layers.length, 3); assert.equal(next.layers[1].name, "One copy"); assert.notEqual(next.layers[1].id, "a");
});
test("remove is idempotent for unknown ids", () => {
  assert.deepEqual(removeLayer(base(), "missing"), base()); assert.equal(removeLayer(base(), "a").layers.length, 1);
});
test("document validation rejects unsupported extra layer properties", () => {
  assert.throws(() => validateLayerDocument({ ...base(), layers: [{ ...base().layers[0], extra: true }] }), /unsupported|invalid/i);
});
test("document validation rejects open polygon rings", () => {
  assert.throws(() => validateLayerDocument({ ...base(), layers: [{ id: "p", kind: "geometry", name: "Polygon", geometry: { type: "Polygon", coordinates: [[[-122.4, 37.7], [-122.3, 37.7], [-122.3, 37.8], [-122.4, 37.75]]] }, visible: true, opacity: 1, minZoom: 0, maxZoom: 24 }] }), /invalid|unsupported/i);
});
