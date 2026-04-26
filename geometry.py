"""
Geometry extraction from IFC.

Principle: one function per concept.
  - bbox_of_element: single element -> ElementBBox (axis-aligned)
  - slab_footprint_of_element: slab -> SlabFootprint (bbox + true 2D polygon)
  - bboxes_for_class: batch helper, returns dict keyed by GlobalId

We use IfcOpenShell's geometry engine to materialize each element's
mesh in world coordinates, then take min/max of its vertices for bbox,
or union the triangles projected to XY for true footprint.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import ifcopenshell
import ifcopenshell.geom
import numpy as np
from shapely import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


@dataclass
class ElementBBox:
    """Axis-aligned bounding box for a single IFC element, world coords."""
    global_id: str
    ifc_class: str
    name: str
    z_min: float
    z_max: float
    x_min: float
    x_max: float
    y_min: float
    y_max: float


@dataclass
class SlabFootprint:
    """Bbox plus true 2D footprint polygon (mesh triangles unioned in XY)."""
    bbox: ElementBBox
    footprint: BaseGeometry  # shapely Polygon or MultiPolygon


def _geom_settings() -> ifcopenshell.geom.settings:
    s = ifcopenshell.geom.settings()
    s.set(s.USE_WORLD_COORDS, True)
    return s


def _bbox_from_verts(global_id, ifc_class, name, verts: np.ndarray) -> ElementBBox:
    mn = verts.min(axis=0)
    mx = verts.max(axis=0)
    return ElementBBox(
        global_id=global_id, ifc_class=ifc_class, name=name,
        x_min=float(mn[0]), x_max=float(mx[0]),
        y_min=float(mn[1]), y_max=float(mx[1]),
        z_min=float(mn[2]), z_max=float(mx[2]),
    )


def bbox_of_element(element, settings=None) -> Optional[ElementBBox]:
    """Compute bbox for a single element. Returns None if no geometry."""
    settings = settings or _geom_settings()
    try:
        shape = ifcopenshell.geom.create_shape(settings, element)
    except Exception:
        return None

    verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
    if verts.size == 0:
        return None
    return _bbox_from_verts(element.GlobalId, element.is_a(), element.Name or "", verts)


def slab_footprint_of_element(element, settings=None) -> Optional[SlabFootprint]:
    """Compute bbox + true 2D footprint polygon for a slab.

    Projects all mesh triangles onto XY and unions them. Handles L-shapes,
    holes, and non-rectangular slabs exactly. Returns None if no geometry.
    """
    settings = settings or _geom_settings()
    try:
        shape = ifcopenshell.geom.create_shape(settings, element)
    except Exception:
        return None

    verts_3d = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
    faces = np.asarray(shape.geometry.faces, dtype=int).reshape(-1, 3)
    if verts_3d.size == 0 or faces.size == 0:
        return None

    bbox = _bbox_from_verts(element.GlobalId, element.is_a(), element.Name or "", verts_3d)

    verts_xy = verts_3d[:, :2]
    triangles = []
    for a, b, c in faces:
        try:
            tri = Polygon([verts_xy[a], verts_xy[b], verts_xy[c]])
            if tri.is_valid and tri.area > 1e-9:
                triangles.append(tri)
        except Exception:
            continue

    if not triangles:
        return None

    footprint = unary_union(triangles)
    return SlabFootprint(bbox=bbox, footprint=footprint)


def bboxes_for_class(ifc_file, ifc_class: str) -> list[ElementBBox]:
    """Compute bboxes for all elements of a given IFC class."""
    settings = _geom_settings()
    results = []
    for el in ifc_file.by_type(ifc_class):
        bb = bbox_of_element(el, settings)
        if bb is not None:
            results.append(bb)
    return results
