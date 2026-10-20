import type { LayerDocument, StudioLayer } from "./types";

export function updateLayer(document: LayerDocument, id: string, patch: Partial<StudioLayer>): LayerDocument {
  return { ...document, layers: document.layers.map((layer) => layer.id === id ? ({ ...layer, ...patch } as StudioLayer) : layer) };
}
export function moveLayer(document: LayerDocument, id: string, direction: "up" | "down"): LayerDocument {
  const index = document.layers.findIndex((layer) => layer.id === id);
  const nextIndex = direction === "up" ? index + 1 : index - 1;
  if (index < 0 || nextIndex < 0 || nextIndex >= document.layers.length) return document;
  const layers = [...document.layers]; [layers[index], layers[nextIndex]] = [layers[nextIndex], layers[index]];
  return { ...document, layers };
}
export function duplicateLayer(document: LayerDocument, id: string): LayerDocument {
  const index = document.layers.findIndex((layer) => layer.id === id);
  if (index < 0) return document;
  const copy = { ...document.layers[index], id: crypto.randomUUID(), name: `${document.layers[index].name} copy` } as StudioLayer;
  const layers = [...document.layers]; layers.splice(index + 1, 0, copy); return { ...document, layers };
}
export function removeLayer(document: LayerDocument, id: string): LayerDocument { return { ...document, layers: document.layers.filter((layer) => layer.id !== id) }; }
export function newLayerId(kind: StudioLayer["kind"]): string { return `${kind}-${crypto.randomUUID()}`; }
