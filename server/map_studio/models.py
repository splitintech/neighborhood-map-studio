"""Strict wire contracts for Map Studio.

The browser receives these contracts from the BFF.  Keeping the shape strict at
the boundary is intentional: a layer document is user editable JSON and must
never become an implicit escape hatch for arbitrary metadata.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, TypeAdapter, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Position = tuple[float, float]


def _position(value: Any) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("position must be [longitude, latitude]")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        raise ValueError("position must contain numbers")
    try:
        result = (float(value[0]), float(value[1]))
    except (TypeError, ValueError) as exc:
        raise ValueError("position must contain numbers") from exc
    if not all(math.isfinite(number) for number in result):
        raise ValueError("position must contain finite numbers")
    if not -180 <= result[0] <= 180 or not -90 <= result[1] <= 90:
        raise ValueError("position is outside longitude/latitude bounds")
    return result


class LayerBase(StrictModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    kind: str
    name: str = Field(min_length=1, max_length=200)
    visible: StrictBool = True
    opacity: StrictFloat = Field(default=1, ge=0, le=1)
    minZoom: StrictFloat = Field(default=0, ge=0, le=24)
    maxZoom: StrictFloat = Field(default=24, ge=0, le=24)
    category: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def zoom_order(self) -> "LayerBase":
        if self.minZoom > self.maxZoom:
            raise ValueError("minZoom must not exceed maxZoom")
        return self


class ArtworkLayer(LayerBase):
    kind: Literal["artwork"]
    assetId: UUID
    position: Position
    width: StrictFloat = Field(gt=0, le=4096)
    height: StrictFloat = Field(gt=0, le=4096)
    rotation: StrictFloat = Field(default=0, ge=-3600, le=3600)

    _position = field_validator("position", mode="before")(_position)


class AnnotationLayer(LayerBase):
    kind: Literal["annotation"]
    text: str = Field(min_length=1, max_length=2000)
    position: Position

    _position = field_validator("position", mode="before")(_position)


class GeometryLayer(LayerBase):
    kind: Literal["geometry"]
    geometry: dict[str, Any]

    @field_validator("geometry")
    @classmethod
    def valid_geojson(cls, value: dict[str, Any]) -> dict[str, Any]:
        if set(value) != {"type", "coordinates"}:
            raise ValueError("geometry must contain only type and coordinates")
        kind = value.get("type")
        if kind not in {"Point", "LineString", "Polygon"}:
            raise ValueError("unsupported geometry type")

        def coordinate(point: Any) -> None:
            _position(point)

        coordinates = value["coordinates"]
        if kind == "Point":
            coordinate(coordinates)
        elif kind == "LineString":
            if not isinstance(coordinates, list) or len(coordinates) < 2:
                raise ValueError("LineString needs at least two positions")
            if len(coordinates) > 5000:
                raise ValueError("LineString is too complex")
            for point in coordinates:
                coordinate(point)
        else:
            if not isinstance(coordinates, list) or len(coordinates) < 1:
                raise ValueError("Polygon needs a ring")
            if len(coordinates) > 64 or sum(len(ring) if isinstance(ring, list) else 0 for ring in coordinates) > 5000:
                raise ValueError("Polygon is too complex")
            for ring in coordinates:
                if not isinstance(ring, list) or len(ring) < 4:
                    raise ValueError("Polygon rings need at least four positions")
                if len(ring) > 2000:
                    raise ValueError("Polygon ring is too complex")
                for point in ring:
                    coordinate(point)
                if list(ring[0]) != list(ring[-1]):
                    raise ValueError("Polygon rings must be closed")
        return value


class BusinessLayer(LayerBase):
    kind: Literal["business"]
    businessId: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    assetId: UUID | None = None
    highlight: Literal["none", "accent", "ring"] = "none"


Layer = Annotated[Union[ArtworkLayer, AnnotationLayer, GeometryLayer, BusinessLayer], Field(discriminator="kind")]


class LayerDocument(StrictModel):
    schemaVersion: Literal[1]
    mapKey: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$")
    theme: Literal["original", "paper", "sage"]
    layers: list[Layer] = Field(max_length=500)

    @model_validator(mode="after")
    def unique_layer_ids(self) -> "LayerDocument":
        ids = [layer.id for layer in self.layers]
        if len(ids) != len(set(ids)):
            raise ValueError("layer ids must be unique")
        return self


class Project(StrictModel):
    mapKey: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$")
    title: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=120)
    publicPath: str = Field(min_length=1, max_length=300)
    center: Position
    sourceRevision: str = Field(min_length=1, max_length=200)

    _center = field_validator("center", mode="before")(_position)


class Business(StrictModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    name: str = Field(min_length=1, max_length=300)
    category: str | None = Field(default=None, max_length=120)
    location: dict[str, Any] | None = None
    logoUrl: str | None = Field(default=None, max_length=2000)

    @field_validator("location")
    @classmethod
    def valid_location(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if set(value) - {"lat", "lng", "precisionNote"} or "lat" not in value or "lng" not in value:
            raise ValueError("location has unsupported fields")
        if "precisionNote" in value and (not isinstance(value["precisionNote"], str) or len(value["precisionNote"]) > 300):
            raise ValueError("precisionNote must be a short string")
        if any(isinstance(value[key], bool) or not isinstance(value[key], (int, float)) for key in ("lat", "lng")):
            raise ValueError("location coordinates must be numbers")
        lat, lng = float(value["lat"]), float(value["lng"])
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError("location is outside latitude/longitude bounds")
        return value


class Asset(StrictModel):
    id: UUID
    name: str = Field(min_length=1, max_length=300)
    altText: str = Field(min_length=1, max_length=1000)
    rights: str = Field(min_length=1, max_length=2000)
    url: str = Field(min_length=1, max_length=4000)
    width: StrictInt = Field(gt=0, le=4096)
    height: StrictInt = Field(gt=0, le=4096)
    state: Literal["ready"]


class ProjectListResponse(StrictModel):
    projects: list[Project]
    isAdmin: bool


class ProjectResponse(StrictModel):
    project: Project
    businesses: list[Business]
    draft: dict[str, Any]
    canEdit: bool


class LeaseRequest(StrictModel):
    clientId: str = Field(min_length=1, max_length=128)


class DraftRequest(StrictModel):
    document: LayerDocument
    expectedRevision: StrictInt = Field(ge=0)
    clientId: str = Field(min_length=1, max_length=128)


class PublishRequest(StrictModel):
    expectedRevision: StrictInt = Field(ge=0)
    clientId: str = Field(min_length=1, max_length=128)


class RollbackRequest(StrictModel):
    versionId: UUID
    clientId: str = Field(min_length=1, max_length=128)


class MemberRequest(StrictModel):
    userId: UUID
    enabled: bool


class AssetUploadRequest(StrictModel):
    name: str = Field(min_length=1, max_length=300)
    altText: str = Field(min_length=1, max_length=1000)
    rights: str = Field(min_length=1, max_length=2000)
    mimeType: str = Field(min_length=1, max_length=100)
    dataBase64: str = Field(min_length=1, max_length=30_000_000)


DOCUMENT_ADAPTER = TypeAdapter(LayerDocument)
