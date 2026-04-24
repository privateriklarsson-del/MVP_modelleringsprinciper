"""
BCF export for violations.

Uses bcf-client (the same library ifctester uses under the hood).
One topic per violation; all topics in one BCF zip.

Components = [wall, related slab], both Selected.
Camera target aimed at the problem (midpoint of the gap).
"""
from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
from bcf.v3.bcfxml import BcfXml

from rules import Violation


def violations_to_bcf(
    violations: list[Violation],
    project_name: str = "IFC Geom Checker",
    author: str = "ifc-geom-checker@jm.se",
) -> bytes:
    """Build a BCF zip in memory and return bytes."""
    bcfxml = BcfXml.create_new(project_name)

    for v in violations:
        topic = bcfxml.add_topic(
            title=f"{v.rule}: {v.element_name or v.global_id}",
            description=v.description,
            author=author,
            topic_type="Geometry",
            topic_status="Open",
        )
        guids = [v.global_id, *v.related_global_ids]
        camera = np.array(v.camera_target, dtype=np.float64)
        topic.add_viewpoint_from_point_and_guids(camera, *guids)

    # bcf-client writes to disk; we stage in a temp file and read bytes back.
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
