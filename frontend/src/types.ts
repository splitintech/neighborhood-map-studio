import { emptyLayerDocument, validateLayerDocument } from "../../shared/contracts";
export { emptyLayerDocument, validateLayerDocument };
export type {
  Coordinate, StudioTheme as MapTheme, StudioGeometry as Geometry, StudioLayer, StudioArtworkLayer as ArtworkLayer,
  StudioAnnotationLayer as AnnotationLayer, StudioGeometryLayer as GeometryLayer, StudioBusinessLayer as BusinessLayer,
  LayerDocument, CanonicalBusiness as Business, StudioAsset as Asset, StudioProject as Project,
} from "../../shared/contracts";
import type { LayerDocument as SharedLayerDocument, StudioAsset, StudioProject, CanonicalBusiness } from "../../shared/contracts";
export type ProjectDetail = { project: StudioProject; businesses: CanonicalBusiness[]; draft: { document: SharedLayerDocument; revision: number }; canEdit: boolean };
export type Version = { id: string; createdAt: string; createdBy: string; revision: number };
export function cloneDocument(document: SharedLayerDocument): SharedLayerDocument { return JSON.parse(JSON.stringify(document)) as SharedLayerDocument; }
