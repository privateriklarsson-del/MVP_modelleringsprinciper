"""
JM TypeID extraction and prefix matching.

Property location: Pset name 'JM', property 'TypeID'.
Value can sit on the instance OR on the element type — get_psets()
walks both, so we don't need to care which.
"""
from __future__ import annotations

import re

import ifcopenshell.util.element


JM_PSET = "JM"
TYPEID_PROP = "TypeID"


def get_jm_type_id(element) -> str | None:
    """Return JM.TypeID for an element, or None if missing."""
    psets = ifcopenshell.util.element.get_psets(element)
    jm = psets.get(JM_PSET)
    if not jm:
        return None
    val = jm.get(TYPEID_PROP)
    if val is None or val == "":
        return None
    return str(val)


def compile_prefix_pattern(prefixes: list[str]) -> re.Pattern:
    """Compile a regex that matches any of the given prefixes at start.

    Example: ['IWS', 'IWC', 'IV'] -> ^(IWS|IWC|IV)
    """
    if not prefixes:
        # Match nothing
        return re.compile(r"$.^")
    escaped = "|".join(re.escape(p) for p in prefixes)
    return re.compile(f"^({escaped})")


def filter_by_typeid_prefix(elements: list, prefixes: list[str]) -> list:
    """Keep elements whose JM.TypeID starts with any of the given prefixes.

    Elements without a JM.TypeID are dropped silently (out of scope).
    """
    pattern = compile_prefix_pattern(prefixes)
    out = []
    for el in elements:
        type_id = get_jm_type_id(el)
        if type_id is None:
            continue
        if pattern.match(type_id):
            out.append(el)
    return out
