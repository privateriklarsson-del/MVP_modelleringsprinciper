"""
Rules for geometric model checking.

Principle: each rule is a pure function.
  - Input: bboxes (+ any element metadata needed)
  - Output: list of Violation objects

No IFC loading here. No UI. Just logic over data structures.
This makes rules unit-testable and swappable.
"""
from __future__ import annotations

from dataclasses import dataclass

from geometry import ElementBBox


@dataclass
class Violation:
    global_id: str
    element_name: str
    rule: str
    description: str
    measured_gap_mm: float


def _is_external(wall_element) -> bool | None:
    """Return True/False if Pset_WallCommon.IsExternal is set, else None."""
    # Walk the element's psets; cheap and dependency-free.
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
    """Return IfcWall elements that are explicitly NOT external.

    If IsExternal is missing, we keep the wall (safer default: check it,
    let user see the result). We only exclude walls where IsExternal=True.
    """
    out = []
    for w in ifc_file.by_type("IfcWall"):
        if _is_external(w) is True:
            continue
        out.append(w)
    return out


def check_walls_reach_slabs(
    wall_bboxes: list[ElementBBox],
    slab_bboxes: list[ElementBBox],
    tolerance_mm: float = 10.0,
    unit_factor_to_mm: float = 1000.0,
) -> list[Violation]:
    """Check that each wall's top reaches a slab above, and bottom reaches a slab below.

    MVP simplification: no XY overlap check. Each wall is matched to the
    nearest slab above and nearest slab below by Z only. This can produce
    false positives when the geometrically-correct slab doesn't exist
    directly above/below (e.g. wall at building edge) — that's expected
    for v1 and is exactly what we want to see on real data.
    """
    violations: list[Violation] = []
    tol = tolerance_mm / unit_factor_to_mm  # assume project is in meters

    for wall in wall_bboxes:
        # Nearest slab above: slab.z_min must be >= wall.z_max (with some tolerance)
        slabs_above = [s for s in slab_bboxes if s.z_min >= wall.z_max - tol]
        slabs_below = [s for s in slab_bboxes if s.z_max <= wall.z_min + tol]

        if slabs_above:
            slab_above = min(slabs_above, key=lambda s: s.z_min - wall.z_max)
            gap = slab_above.z_min - wall.z_max
            if abs(gap) > tol:
                violations.append(Violation(
                    global_id=wall.global_id,
                    element_name=wall.name,
                    rule="wall_top_reaches_slab_above",
                    description=(
                        f"Vägg når inte UK bjälklag. Gap: {gap * unit_factor_to_mm:.1f} mm"
                    ),
                    measured_gap_mm=gap * unit_factor_to_mm,
                ))

        if slabs_below:
            slab_below = max(slabs_below, key=lambda s: s.z_max - wall.z_min)
            gap = wall.z_min - slab_below.z_max
            if abs(gap) > tol:
                violations.append(Violation(
                    global_id=wall.global_id,
                    element_name=wall.name,
                    rule="wall_bottom_reaches_slab_below",
                    description=(
                        f"Vägg når inte ÖK bjälklag. Gap: {gap * unit_factor_to_mm:.1f} mm"
                    ),
                    measured_gap_mm=gap * unit_factor_to_mm,
                ))

    return violations
