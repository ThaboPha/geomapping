"""Helpers shared across pages."""
from __future__ import annotations

import pandas as pd
import pydeck as pdk
import streamlit as st

# Palette (RGB) used on maps; matches .streamlit/config.toml.
INK = [22, 35, 46]
NETWORK = [31, 95, 139]
OK = [26, 127, 92]
WARN = [214, 140, 26]
RISK = [190, 58, 52]
MUTED = [140, 150, 158]

STANDARD_CATEGORY = {"GP": "GP", "Core Specialist": "Core Specialist", "Other Specialist": "Other Specialist",
                     "Hospital": "Hospital", "Day Hospital": "Hospital"}


def select_option(src, member=None, key="search_option"):
    """Use a validated member option or an independently selected planning option."""
    opts = src.options()
    names = dict(zip(opts.ProdCode, opts.OptionName))
    codes = [member['ProdCode']] if member else list(opts.ProdCode)
    if not codes:
        st.warning("No current network product options are available in the data source.")
        return None
    saved = st.session_state.get('selected_benefit_option')
    prod = st.selectbox("Benefit option", codes,
        index=codes.index(saved) if saved in codes else 0,
        format_func=lambda code: names.get(code, code), disabled=bool(member), key=key,
        help="Loaded from membership when provided; otherwise choose an option to explore its network.")
    st.session_state['selected_benefit_option'] = prod
    return prod


def standard_km(standards: pd.DataFrame, category: str, geotype: str) -> float | None:
    cat = STANDARD_CATEGORY.get(category, category)
    row = standards[(standards.ProviderCategory == cat) & (standards.Geotype == geotype)]
    return None if row.empty else float(row.RadiusKm.iloc[0])


def deck(layers, lat: float, lon: float, zoom: float = 10, tooltip: dict | None = None) -> pdk.Deck:
    return pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom),
        map_provider="carto",
        map_style="light",
        tooltip=tooltip,
    )


def zoom_for_km(km: float) -> float:
    for limit, z in ((3, 13), (7, 12), (15, 11), (30, 10), (60, 9), (120, 8), (250, 7)):
        if km <= limit:
            return z
    return 6

