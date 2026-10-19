"""Bonitas network geo-mapping: Streamlit entry point (local or Databricks Apps)."""
import streamlit as st
from pathlib import Path

from geomap import config
from geomap.data import get_source
from geomap.membership import render_membership
from geomap.views import alignment, coverage, lookup, quality

st.set_page_config(page_title="Network geo-mapping", page_icon=":material/map:", layout="wide")

pages = [
    st.Page(lookup.render, title="Find a provider", icon=":material/person_pin_circle:", url_path="lookup", default=True),
    st.Page(coverage.render, title="Member access", icon=":material/radar:", url_path="coverage"),
    st.Page(alignment.render, title="Specialists and hospitals", icon=":material/local_hospital:", url_path="alignment"),
    st.Page(quality.render, title="Data quality", icon=":material/fact_check:", url_path="quality"),
]

with st.sidebar:
    logo = Path(__file__).parent / 'assets' / 'pha_logo.jpg'
    if logo.exists():
        st.image(str(logo), width=200)
    st.markdown("**Network geo-mapping**")
    try:
        src = get_source()
        if getattr(src,'is_snapshot',False) is True:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            captured=datetime.fromisoformat(src.manifest['completed_at']).astimezone(ZoneInfo('Africa/Johannesburg'))
            st.info(f"Snapshot data · {captured:%d %b %Y %H:%M} SAST")
            st.caption('Databricks is not queried while browsing. Data changes appear after the next manually validated snapshot.')
        else:
            st.caption(f"Live Databricks: {config.CATALOG}.{config.SCHEMA}")
    except Exception as exc:  # surface connection problems instead of a stack trace
        st.error(f"Cannot load data: {exc}")
        st.stop()

    render_membership(src)

st.navigation(pages).run()
