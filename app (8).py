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
from geometry import ElementBBox, bboxes_for_class
from rules import check_walls_reach_slabs, filter_interior_walls


@st.cache_data(show_spinner=False)
def load_and_extract(ifc_bytes: bytes) -> tuple[str, int, list[ElementBBox], list[ElementBBox]]:
    """Open IFC and extract bboxes. Cached on bytes content.

    Returns: (schema, total_wall_count, interior_wall_bboxes, slab_bboxes)
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp:
        tmp.write(ifc_bytes)
        tmp_path = Path(tmp.name)
    try:
        ifc = ifcopenshell.open(str(tmp_path))
        total_walls = len(ifc.by_type("IfcWall"))

        interior_wall_ids = {w.GlobalId for w in filter_interior_walls(ifc)}
        all_wall_bboxes = bboxes_for_class(ifc, "IfcWall")
        wall_bboxes = [b for b in all_wall_bboxes if b.global_id in interior_wall_ids]
        slab_bboxes = bboxes_for_class(ifc, "IfcSlab")
        return ifc.schema, total_walls, wall_bboxes, slab_bboxes
    finally:
        tmp_path.unlink(missing_ok=True)


st.set_page_config(page_title="IFC Geom Checker", layout="wide")
st.title("IFC geometrisk kontroll — MVP")
st.caption("Checker: vägg når UK/ÖK bjälklag")

uploaded = st.file_uploader("Ladda upp IFC-fil", type=["ifc"])

col_tol, col_ov = st.columns(2)
tol_mm = col_tol.number_input(
    "Tolerans Z (mm)", min_value=1.0, max_value=100.0, value=10.0, step=1.0,
    help="Hur stort Z-gap som tillåts innan det flaggas.",
)
min_overlap = col_ov.number_input(
    "Min XY-överlapp (m²)", min_value=0.001, max_value=1.0, value=0.01, step=0.01,
    format="%.3f",
    help=(
        "Minsta yta där vägg-footprint och slab-footprint överlappar i planet "
        "för att de ska matchas. 0.01 m² = ~100 cm² filtrerar bort kant-träffar."
    ),
)

if uploaded is None:
    st.info("Ladda upp en IFC för att starta.")
    st.stop()

# getvalue() works regardless of read-pointer state (important for rerun)
ifc_bytes = uploaded.getvalue()
file_hash = hashlib.md5(ifc_bytes).hexdigest()[:8]

with st.spinner("Läser IFC och extraherar geometri (cachas per fil)..."):
    schema, total_walls, wall_bboxes, slab_bboxes = load_and_extract(ifc_bytes)

col_a, col_b, col_c, col_d = st.columns(4)
col_a.metric("IFC-schema", schema)
col_b.metric("IfcWall (totalt)", total_walls)
col_c.metric("Innerväggar", len(wall_bboxes))
col_d.metric("IfcSlab", len(slab_bboxes))

st.caption(f"Fil-hash: `{file_hash}` — tuning-parametrar kör bara om regeln, inte geometri-extraktionen.")

violations = check_walls_reach_slabs(
    wall_bboxes, slab_bboxes,
    tolerance_mm=tol_mm,
    min_xy_overlap_m2=min_overlap,
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
