"""
BCF export for violations.

Groups violations by related slab: one BCF topic per slab, with all
offending walls + that slab as selected components.
"""
from __future__ import annotations

import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from bcf.v3.bcfxml import BcfXml

from rules import Violation


def _group_by_slab(violations: list[Violation]) -> dict[str, list[Violation]]:
    """Group violations by the first related GlobalId (= matched slab)."""
    groups: dict[str, list[Violation]] = defaultdict(list)
    for v in violations:
        if not v.related_global_ids:
            continue  # skip malformed violations
        slab_guid = v.related_global_ids[0]
        groups[slab_guid].append(v)
    return dict(groups)


def _topic_title(slab_guid: str, violations: list[Violation]) -> str:
    n = len(violations)
    return f"{n} vägg{'ar' if n != 1 else ''} når inte bjälklag"


def _topic_description(slab_guid: str, violations: list[Violation]) -> str:
    lines = [f"Bjälklag GlobalId: {slab_guid}", f"Antal väggar: {len(violations)}", ""]
    # Sort: worst gap first
    sorted_v = sorted(violations, key=lambda v: abs(v.measured_gap_mm), reverse=True)
    for v in sorted_v:
        rule_short = "top" if v.rule.endswith("above") else "bot"
        name = v.element_name or v.global_id[:8]
        lines.append(f"  [{rule_short}] {name} — gap {v.measured_gap_mm:+.1f} mm")
    return "\n".join(lines)


def _camera_target_for_group(violations: list[Violation]) -> np.ndarray:
    """Average camera target across the group — aims near the shared slab."""
    arr = np.array([v.camera_target for v in violations], dtype=np.float64)
    return arr.mean(axis=0)


def violations_to_bcf(
    violations: list[Violation],
    project_name: str = "IFC Geom Checker",
    author: str = "ifc-geom-checker@jm.se",
) -> bytes:
    """Build a BCF zip in memory. One topic per slab."""
    bcfxml = BcfXml.create_new(project_name)

    groups = _group_by_slab(violations)

    for slab_guid, group in groups.items():
        topic = bcfxml.add_topic(
            title=_topic_title(slab_guid, group),
            description=_topic_description(slab_guid, group),
            author=author,
            topic_type="Geometry",
            topic_status="Open",
        )
        # All offending walls + the shared slab, all selected
        wall_guids = [v.global_id for v in group]
        guids = [slab_guid, *wall_guids]
        camera = _camera_target_for_group(group)
        topic.add_viewpoint_from_point_and_guids(camera, *guids)

    with tempfile.NamedTemporaryFile(suffix=".bcf", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        bcfxml.save(tmp_path)
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)


def default_bcf_filename() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"geom_check_{ts}.bcf"
