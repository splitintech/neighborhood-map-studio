import { useEffect, useRef } from "react";
import * as L from "leaflet";
import { TerraDraw, TerraDrawLineStringMode, TerraDrawPointMode, TerraDrawPolygonMode, TerraDrawSelectMode, type GeoJSONStoreFeatures } from "terra-draw";
import { TerraDrawLeafletAdapter } from "terra-draw-leaflet-adapter";
// The shared renderer is intentionally kept outside the frontend package. The
// standalone Daytona app owns the map shell, while ../shared owns canonical
// layer validation and Leaflet panes/assets.
import { mountStudioLayers } from "../../shared/leaflet";
import type { Asset, Business, Geometry, LayerDocument, Project } from "./types";
import "leaflet/dist/leaflet.css";
import "../../shared/layers.css";

type Tool = "select" | "annotation" | "point" | "line" | "polygon";
type Props = {
  document: LayerDocument;
  project: Project | null;
  businesses: Business[];
  assets: Asset[];
  selectedId: string | null;
  tool: Tool;
  editable: boolean;
  zoom: number;
  onSelect: (id: string) => void;
  onMove: (id: string, position: [number, number]) => void;
  onGeometryFinished: (geometry: Geometry) => void;
  onAnnotation: (position: [number, number]) => void;
  consentGranted: boolean;
  onRequestConsent: () => void;
};

function asGeometry(feature: GeoJSONStoreFeatures): Geometry | null {
  const geometry = feature.geometry;
  if (geometry.type === "Point") return { type: "Point", coordinates: [geometry.coordinates[0], geometry.coordinates[1]] };
  if (geometry.type === "LineString") return { type: "LineString", coordinates: geometry.coordinates.map((point) => [point[0], point[1]]) };
  if (geometry.type === "Polygon") return { type: "Polygon", coordinates: geometry.coordinates.map((ring) => ring.map((point) => [point[0], point[1]])) };
  return null;
}

export default function RealMap({ document: mapDocument, project, businesses, assets, selectedId, tool, editable, zoom, onSelect, onMove, onGeometryFinished, onAnnotation, consentGranted, onRequestConsent }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerMountRef = useRef<{ update: (input: any) => void; dispose: () => void } | null>(null);
  const drawRef = useRef<TerraDraw | null>(null);
  const annotationHandlerRef = useRef<((event: L.LeafletMouseEvent) => void) | null>(null);
  const callbacksRef = useRef({ onSelect, onMove, onGeometryFinished, onAnnotation });
  callbacksRef.current = { onSelect, onMove, onGeometryFinished, onAnnotation };

  useEffect(() => {
    if (!hostRef.current || !project || !consentGranted) return;
    const center = project.center;
    const map = L.map(hostRef.current, { center: [center[1], center[0]], zoom, zoomControl: false, doubleClickZoom: true, attributionControl: true });
    L.control.zoom({ position: "bottomright" }).addTo(map);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map);
    mapRef.current = map;
    layerMountRef.current = mountStudioLayers({ L, map, document: mapDocument, businesses, assets, editable, onSelect: (layer) => callbacksRef.current.onSelect(layer.id), onMove: (layer, position) => callbacksRef.current.onMove(layer.id, [position[0], position[1]]) });
    const adapter = new TerraDrawLeafletAdapter({ lib: L, map, coordinatePrecision: 6 });
    const draw = new TerraDraw({ adapter, modes: [new TerraDrawSelectMode(), new TerraDrawPointMode(), new TerraDrawLineStringMode(), new TerraDrawPolygonMode()] });
    draw.start();
    const finish = (id: string | number) => { const feature = draw.getSnapshotFeature(id); const geometry = feature ? asGeometry(feature) : null; if (geometry) callbacksRef.current.onGeometryFinished(geometry); draw.removeFeatures([id]); draw.setMode("select"); };
    const select = (id: string | number) => callbacksRef.current.onSelect(String(id));
    draw.on("finish", finish); draw.on("select", select);
    drawRef.current = draw;
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => map.invalidateSize({ pan: false, animate: false }));
    if (resizeObserver && hostRef.current) resizeObserver.observe(hostRef.current);
    return () => { resizeObserver?.disconnect(); if (annotationHandlerRef.current) map.off("click", annotationHandlerRef.current); layerMountRef.current?.dispose(); draw.stop(); map.remove(); mapRef.current = null; layerMountRef.current = null; drawRef.current = null; };
    // A new project gets a new map instance; edits update through the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.mapKey, consentGranted]);

  useEffect(() => { const map = mapRef.current; if (!map) return; map.setZoom(zoom); }, [zoom]);
  useEffect(() => { layerMountRef.current?.update({ document: mapDocument, businesses, assets, editable }); }, [mapDocument, businesses, assets, editable]);
  useEffect(() => {
    const map = mapRef.current; const draw = drawRef.current; if (!map || !draw) return;
    if (annotationHandlerRef.current) { map.off("click", annotationHandlerRef.current); annotationHandlerRef.current = null; }
    if (!editable) { draw.setMode("select"); return; }
    if (tool === "annotation") { draw.setMode("select"); const handler = (event: L.LeafletMouseEvent) => callbacksRef.current.onAnnotation([event.latlng.lng, event.latlng.lat]); annotationHandlerRef.current = handler; map.on("click", handler); return () => { map.off("click", handler); }; }
    const mode = tool === "point" ? "point" : tool === "line" ? "linestring" : tool === "polygon" ? "polygon" : "select";
    draw.setMode(mode);
  }, [tool, editable]);

  return <div ref={hostRef} className={`map-stage leaflet-host ${mapDocument.theme}`} aria-label="Interactive OpenStreetMap editor">{!consentGranted && <div className="map-consent-card"><div className="map-consent-icon">⌖</div><strong>Enable the street map</strong><p>Map Studio uses OpenStreetMap tiles to show streets around your private project. Nothing is loaded until you allow map tiles.</p><button className="primary-btn" onClick={onRequestConsent}>Enable map tiles</button></div>}{consentGranted && <><div className="map-chip map-live-chip"><span className="map-live-dot" />Live street map · {project?.city ?? "Map"}</div>{tool !== "select" && <div className="map-chip map-instruction">{tool === "annotation" ? "Click the map to place an annotation" : `Draw a ${tool}; finish with a double-click`}</div>}</>}</div>;
}
