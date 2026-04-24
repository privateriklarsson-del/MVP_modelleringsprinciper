"""
Streamlit UI for geometric IFC checks.

Keep it thin: UI only. All logic lives in geometry.py and rules.py.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import ifcopenshell
import pandas as pd
import streamlit as st

from geometry import bboxes_for_class
from rules import check_walls_reach_slabs, filter_interior_walls


st.set_page_config(page_title="IFC Geom Checker", layout="wide")
st.title("IFC geometrisk kontroll — MVP")
st.caption("Checker: vägg når UK/ÖK bjälklag")

uploaded = st.file_uploader("Ladda upp IFC-fil", type=["ifc"])
tol_mm = st.number_input("Tolerans (mm)", min_value=1.0, max_value=100.0, value=10.0, step=1.0)

if uploaded is None:
    st.info("Ladda upp en IFC för att starta.")
    st.stop()

# Persist upload to a temp path so ifcopenshell can open it by path.
with tempfile.NamedTemporaryFile(delete=False, suffix=".ifc") as tmp:
    tmp.write(uploaded.read())
    tmp_path = Path(tmp.name)

with st.spinner("Läser IFC..."):
    ifc = ifcopenshell.open(str(tmp_path))

col_a, col_b, col_c = st.columns(3)
col_a.metric("IFC-schema", ifc.schema)
col_b.metric("IfcWall (totalt)", len(ifc.by_type("IfcWall")))
col_c.metric("IfcSlab (totalt)", len(ifc.by_type("IfcSlab")))

with st.spinner("Beräknar geometri (kan ta en stund)..."):
    interior_walls = filter_interior_walls(ifc)
    interior_wall_ids = {w.GlobalId for w in interior_walls}

    all_wall_bboxes = bboxes_for_class(ifc, "IfcWall")
    wall_bboxes = [b for b in all_wall_bboxes if b.global_id in interior_wall_ids]
    slab_bboxes = bboxes_for_class(ifc, "IfcSlab")

st.write(
    f"Bearbetade **{len(wall_bboxes)} innerväggar** "
    f"(av {len(all_wall_bboxes)} IfcWall totalt) "
    f"och **{len(slab_bboxes)} bjälklag**."
)

violations = check_walls_reach_slabs(wall_bboxes, slab_bboxes, tolerance_mm=tol_mm)

st.subheader("Resultat")
if not violations:
    st.success("Inga avvikelser funna.")
else:
    st.error(f"{len(violations)} avvikelser hittades.")
    df = pd.DataFrame([v.__dict__ for v in violations])
    st.dataframe(df, use_container_width=True)

    with st.expander("Fördelning per regel"):
        st.bar_chart(df["rule"].value_counts())
