"""
Rules for geometric model checking.

Principle: each rule is a pure function.
  - Input: bboxes (+ slab footprints + any element metadata needed)
  - Output: list of Violation objects

A Violation carries enough info to generate a BCF topic:
  - GlobalIds of the offending element + related context element
  - A camera target position pointing at the problem
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shapely import Point

from geometry import ElementBBox, SlabFootprint


@dataclass
class Violation:
    global_id: str
    element_name: str
    rule: str
    description: str
    measured_gap_mm: float
    related_global_ids: list[str] = field(default_factory=list)
    camera_target: tuple[float, float, float] = (0.0, 0.0, 0.0)


def _is_external(wall_element) -> bool | None:
    for rel in getattr(wall_element, "IsDefinedBy", []) or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        pset = rel.RelatingPropertyDefinition
        if not pset.is_a("IfcPropertySet"):
            continue
        if pset.Name != "Pset_WallCommon":
            continue
        for prop in pset.HasProperties:
            if prop.Name == "IsExternal" and prop.is_a("IfcPropertySingleValue"):
                val = prop.NominalValue
                if val is not None:
                    return bool(val.wrappedValue)
    return None


def filter_interior_walls(ifc_file) -> list:
    out = []
    for w in ifc_file.by_type("IfcWall"):
        if _is_external(w) is True:
            continue
        out.append(w)
    return out


def _wall_center_xy(wall: ElementBBox) -> tuple[float, float]:
    return ((wall.x_min + wall.x_max) / 2.0, (wall.y_min + wall.y_max) / 2.0)


def _wall_center_in_slab_polygon(wall: ElementBBox, slab: SlabFootprint) -> bool:
    """True if wall's XY centre lies inside slab's true 2D footprint polygon.

    Replaces the old AABB-based check. A long balcony slab whose AABB extends
    far in one direction will no longer falsely match walls under empty
    parts of the AABB — only walls with centre inside the actual slab
    geometry pass.
    """
    cx, cy = _wall_center_xy(wall)
    # covers() includes boundary; contains() excludes it. covers() is safer
    # for walls that align with slab edges.
    return slab.footprint.covers(Point(cx, cy))


def check_walls_reach_slabs(
    wall_bboxes: list[ElementBBox],
    slab_footprints: list[SlabFootprint],
    tolerance_mm: float = 10.0,
    max_z_gap_mm: float = 500.0,
    unit_factor_to_mm: float = 1000.0,
) -> list[Violation]:
    """Check walls reach slabs above and below.

    Matching:
      1. Wall's XY centre must lie inside the slab's true 2D footprint polygon.
      2. Slab must be within max_z_gap_mm of the wall's top (above) or bottom
         (below). Prevents matching against slabs on the wrong floor when the
         correct floor's slab is missing or has a hole at the wall's position.
    From valid candidates, pick the nearest in Z above and below.
    """
    violations: list[Violation] = []
    tol = tolerance_mm / unit_factor_to_mm
    max_gap = max_z_gap_mm / unit_factor_to_mm

    for wall in wall_bboxes:
        cx, cy = _wall_center_xy(wall)

        # Real-geometry sanity check: wall centre must lie inside the slab's
        # true footprint, not just its AABB.
        candidates = [
            sf for sf in slab_footprints
            if _wall_center_in_slab_polygon(wall, sf)
        ]

        # Hard Z-gap limit: only consider slabs reasonably close in height.
        # If the correct slab is missing or has a hole, we report nothing
        # rather than matching against a wrong-floor slab.
        slabs_above = [
            sf for sf in candidates
            if -tol <= sf.bbox.z_min - wall.z_max <= max_gap
        ]
        slabs_below = [
            sf for sf in candidates
            if -tol <= wall.z_min - sf.bbox.z_max <= max_gap
        ]

        if slabs_above:
            slab_above = min(slabs_above, key=lambda sf: sf.bbox.z_min - wall.z_max)
            gap = slab_above.bbox.z_min - wall.z_max
            if abs(gap) > tol:
                violations.append(Violation(
                    global_id=wall.global_id,
                    element_name=wall.name,
                    rule="wall_top_reaches_slab_above",
                    description=(
                        f"Vägg når inte UK bjälklag. Gap: {gap * unit_factor_to_mm:.1f} mm. "
                        f"Matchad platta: {slab_above.bbox.global_id}."
                    ),
                    measured_gap_mm=gap * unit_factor_to_mm,
                    related_global_ids=[slab_above.bbox.global_id],
                    camera_target=(cx, cy, (wall.z_max + slab_above.bbox.z_min) / 2.0),
                ))

        if slabs_below:
            slab_below = max(slabs_below, key=lambda sf: sf.bbox.z_max - wall.z_min)
            gap = wall.z_min - slab_below.bbox.z_max
            if abs(gap) > tol:
                violations.append(Violation(
                    global_id=wall.global_id,
                    element_name=wall.name,
                    rule="wall_bottom_reaches_slab_below",
                    description=(
                        f"Vägg når inte ÖK bjälklag. Gap: {gap * unit_factor_to_mm:.1f} mm. "
                        f"Matchad platta: {slab_below.bbox.global_id}."
                    ),
                    measured_gap_mm=gap * unit_factor_to_mm,
                    related_global_ids=[slab_below.bbox.global_id],
                    camera_target=(cx, cy, (wall.z_min + slab_below.bbox.z_max) / 2.0),
                ))

    return violations


def check_walls_clash_slabs(
    wall_bboxes: list[ElementBBox],
    slab_footprints: list[SlabFootprint],
    tolerance_mm: float = 20.0,
    unit_factor_to_mm: float = 1000.0,
) -> list[Violation]:
    """Check walls don't physically overlap (clash) with slabs in 3D.

    Matching:
      1. Wall's XY centre must lie inside the slab's true 2D footprint.
      2. Z-overlap between wall and slab must exceed tolerance_mm.

    A small intrusion (a few mm) is normal modelling imprecision. Larger
    overlap means the wall extends through the slab and is wrong.
    """
    violations: list[Violation] = []
    tol = tolerance_mm / unit_factor_to_mm

    for wall in wall_bboxes:
        cx, cy = _wall_center_xy(wall)

        candidates = [
            sf for sf in slab_footprints
            if _wall_center_in_slab_polygon(wall, sf)
        ]

        for slab in candidates:
            z_overlap = (
                min(wall.z_max, slab.bbox.z_max)
                - max(wall.z_min, slab.bbox.z_min)
            )
            if z_overlap <= tol:
                continue

            # Camera target: middle of the overlap zone
            overlap_z = (
                max(wall.z_min, slab.bbox.z_min)
                + min(wall.z_max, slab.bbox.z_max)
            ) / 2.0

            violations.append(Violation(
                global_id=wall.global_id,
                element_name=wall.name,
                rule="wall_clash_with_slab",
                description=(
                    f"Vägg krockar med bjälklag. Överlapp: "
                    f"{z_overlap * unit_factor_to_mm:.1f} mm. "
                    f"Matchad platta: {slab.bbox.global_id}."
                ),
                measured_gap_mm=z_overlap * unit_factor_to_mm,
                related_global_ids=[slab.bbox.global_id],
                camera_target=(cx, cy, overlap_z),
            ))

    return violations
