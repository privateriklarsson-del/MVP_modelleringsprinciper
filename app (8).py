"""
Streamlit UI for geometric IFC checks.

Keep it thin: UI only. All logic lives in geometry.py, rules.py, bcf_export.py.

Performance: IFC load + geometry extraction is cached on file contents,
so tuning parameters re-run only the cheap rule evaluation, not the
30–60s geometry step.
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import ifcopenshell
import pandas as pd
import streamlit as st

from bcf_export import default_bcf_filename, violations_to_bcf
from classification import filter_by_typeid_prefix
from geometry import ElementBBox, SlabFootprint, bbox_of_element, slab_footprint_of_element
from rules import check_walls_reach_slabs, filter_interior_walls


WALL_PREFIXES = ["IWS", "IWC", "IV"]
DEFAULT_MIN_SLAB_AREA_M2 = 3.0


@st.cache_data(show_spinner=False)
def load_and_extract(
    ifc_bytes: bytes,
    wall_prefixes: tuple[str, ...],
    min_slab_area_m2: float,
) -> tuple[str, dict, list[ElementBBox], list[SlabFootprint]]:
    """Open IFC, filter elements, extract bboxes + slab footprints.

    Walls: interior + JM.TypeID prefix match.
    Slabs: footprint area (true polygon) >= min_slab_area_m2.

    Cached on (file content, wall_prefixes, min_slab_area_m2).
    """
    import ifcopenshell.geom

    with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp:
        tmp.write(ifc_bytes)
        tmp_path = Path(tmp.name)
    try:
        ifc = ifcopenshell.open(str(tmp_path))

        # Walls: interior filter THEN typeid prefix filter (cheap before bbox)
        all_walls = ifc.by_type("IfcWall")
        interior_wall_ids = {w.GlobalId for w in filter_interior_walls(ifc)}
        interior_walls = [w for w in all_walls if w.GlobalId in interior_wall_ids]
        scope_walls = filter_by_typeid_prefix(interior_walls, list(wall_prefixes))

        all_slabs = ifc.by_type("IfcSlab")

        settings = ifcopenshell.geom.settings()
        settings.set(settings.USE_WORLD_COORDS, True)

        wall_bboxes = []
        for w in scope_walls:
            bb = bbox_of_element(w, settings)
            if bb is not None:
                wall_bboxes.append(bb)

        slab_footprints = []
        slab_dropped_small = 0
        for s in all_slabs:
            sf = slab_footprint_of_element(s, settings)
            if sf is None:
                continue
            # Filter on TRUE polygon area, not AABB area
            if sf.footprint.area < min_slab_area_m2:
                slab_dropped_small += 1
                continue
            slab_footprints.append(sf)

        counts = {
            "wall_total": len(all_walls),
            "wall_interior": len(interior_walls),
            "wall_in_scope": len(wall_bboxes),
            "slab_total": len(all_slabs),
            "slab_in_scope": len(slab_footprints),
            "slab_dropped_small": slab_dropped_small,
        }
        return ifc.schema, counts, wall_bboxes, slab_footprints
    finally:
        tmp_path.unlink(missing_ok=True)


st.set_page_config(page_title="IFC Geom Checker", layout="wide")
st.title("IFC geometrisk kontroll — MVP")
st.caption("Checker: vägg når UK/ÖK bjälklag")

uploaded = st.file_uploader("Ladda upp IFC-fil", type=["ifc"])

col_tol, col_maxgap, col_area = st.columns(3)
tol_mm = col_tol.number_input(
    "Tolerans Z (mm)", min_value=1.0, max_value=100.0, value=10.0, step=1.0,
    help="Hur stort Z-gap som tillåts innan det flaggas som avvikelse.",
)
max_z_gap_mm = col_maxgap.number_input(
    "Max sökavstånd Z (mm)", min_value=50.0, max_value=2000.0, value=500.0, step=50.0,
    help=(
        "Slabs längre bort i Z än så här ignoreras helt. "
        "Förhindrar matchning mot slab på fel våning."
    ),
)
min_slab_area = col_area.number_input(
    "Min slab-area (m²)", min_value=0.5, max_value=50.0,
    value=DEFAULT_MIN_SLAB_AREA_M2, step=0.5,
    help="Slabs mindre än så här (verklig footprint-area) skippas.",
)

if uploaded is None:
    st.info("Ladda upp en IFC för att starta.")
    st.stop()

# getvalue() works regardless of read-pointer state (important for rerun)
ifc_bytes = uploaded.getvalue()
file_hash = hashlib.md5(ifc_bytes).hexdigest()[:8]

with st.spinner("Läser IFC och extraherar geometri (cachas per fil)..."):
    schema, counts, wall_bboxes, slab_footprints = load_and_extract(
        ifc_bytes, tuple(WALL_PREFIXES), float(min_slab_area),
    )

col_a, col_b, col_c, col_d = st.columns(4)
col_a.metric("IFC-schema", schema)
col_b.metric(
    "Väggar i scope",
    counts["wall_in_scope"],
    help=(
        f"Filtrerade prefix: {', '.join(WALL_PREFIXES)}. "
        f"Totalt {counts['wall_total']} IfcWall, varav {counts['wall_interior']} innerväggar."
    ),
)
col_c.metric(
    "Slabs i scope",
    counts["slab_in_scope"],
    help=(
        f"Filter: footprint-area ≥ {min_slab_area:.1f} m². "
        f"Totalt {counts['slab_total']} IfcSlab, "
        f"{counts['slab_dropped_small']} skippade som för små."
    ),
)
col_d.metric("Fil-hash", file_hash)

st.caption(
    f"Väggar: JM.TypeID matchande {WALL_PREFIXES}. "
    f"Slabs: footprint ≥ {min_slab_area:.1f} m². Övriga skippas."
)

violations = check_walls_reach_slabs(
    wall_bboxes, slab_footprints,
    tolerance_mm=tol_mm,
    max_z_gap_mm=max_z_gap_mm,
)

st.subheader("Resultat")
if not violations:
    st.success("Inga avvikelser funna.")
else:
    st.error(f"{len(violations)} avvikelser hittades.")

    rows = [
        {
            "global_id": v.global_id,
            "element_name": v.element_name,
            "rule": v.rule,
            "measured_gap_mm": round(v.measured_gap_mm, 1),
            "description": v.description,
        }
        for v in violations
    ]
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)

    with st.expander("Fördelning per regel"):
        st.bar_chart(df["rule"].value_counts())

    with st.spinner("Genererar BCF..."):
        bcf_bytes = violations_to_bcf(violations)

    st.download_button(
        label="Ladda ner BCF",
        data=bcf_bytes,
        file_name=default_bcf_filename(),
        mime="application/octet-stream",
    )
