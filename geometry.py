"""
Geometry extraction from IFC.

Principle: one function per concept.
  - bbox_of_element: single element -> (min_xyz, max_xyz)
  - bboxes_for_class: batch helper, returns dict keyed by GlobalId

We use IfcOpenShell's geometry engine to materialize each element's
mesh in world coordinates, then take min/max of its vertices.
"""
from __future__ import annotations

from dataclasses import dataclass

import ifcopenshell
import ifcopenshell.geom
import numpy as np


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


def _geom_settings() -> ifcopenshell.geom.settings:
    s = ifcopenshell.geom.settings()
    s.set(s.USE_WORLD_COORDS, True)
    return s


def bbox_of_element(element, settings=None) -> ElementBBox | None:
    """Compute bbox for a single element. Returns None if no geometry."""
    settings = settings or _geom_settings()
    try:
        shape = ifcopenshell.geom.create_shape(settings, element)
    except Exception:
        return None

    verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
    if verts.size == 0:
        return None

    mn = verts.min(axis=0)
    mx = verts.max(axis=0)
    return ElementBBox(
        global_id=element.GlobalId,
        ifc_class=element.is_a(),
        name=element.Name or "",
        x_min=float(mn[0]), x_max=float(mx[0]),
        y_min=float(mn[1]), y_max=float(mx[1]),
        z_min=float(mn[2]), z_max=float(mx[2]),
    )


def bboxes_for_class(ifc_file, ifc_class: str) -> list[ElementBBox]:
    """Compute bboxes for all elements of a given IFC class."""
    settings = _geom_settings()
    results = []
    for el in ifc_file.by_type(ifc_class):
        bb = bbox_of_element(el, settings)
        if bb is not None:
            results.append(bb)
    return results
