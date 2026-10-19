"""Address and geocode quality: what can and cannot be mapped reliably."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from ..data import get_source

FLAG_FIX = {
    "0 OK": "Nothing to do.",
    "1 No street address": "Capture a street address on PracAddr (AddrType S).",
    "2 Postal address in street field": "Replace the PO Box / Private Bag with the physical address.",
    "3 No street line": "Add street number and name.",
    "4 No suburb or town": "Add suburb and town.",
    "5 No postcode": "Add the 4-digit postcode.",
}


def render():
    src = get_source()
    st.title("Data quality")
    st.caption("Distances are only as good as the address behind them. Fix these with Provider Networks.")
    details = src.provider_location_quality()
    network_only = st.toggle("Network providers only", value=True)
    if network_only:
        details = details[details.IsNetworkProvider == 1]
    details = details.copy()
    details['AddrQualityFlag'] = details.AddrQualityFlag.fillna('Unknown address quality')
    details['MatchLevel'] = details.MatchLevel.where(details.HasCoordinates, 'Not geocoded')
    aq = details.groupby(['ProviderCategory', 'IsNetworkProvider', 'AddrQualityFlag', 'MatchLevel'], dropna=False).size().rename('Practices').reset_index()
    total = int(aq.Practices.sum())
    if total == 0:
        st.info("No practices in this selection.")
        return

    street = int(aq.loc[aq.MatchLevel == "Street", "Practices"].sum())
    ungeo = int((~details.HasCoordinates).sum())
    flagged = int(aq.loc[aq.AddrQualityFlag != "0 OK", "Practices"].sum())
    c = st.columns(4)
    c[0].metric("Practices", f"{total:,}")
    c[1].metric("Mapped to street level", f"{100 * street / total:.1f}%")
    c[2].metric("Not on the map", f"{ungeo:,}")
    c[3].metric("Address needs fixing", f"{flagged:,}")
    st.caption(f"{int(details.HasCoordinates.sum()):,} practices have both valid South African coordinates. Source coordinates without street-level verification remain approximate.")

    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Location accuracy")
        ml = aq.groupby(["ProviderCategory", "MatchLevel"]).Practices.sum().reset_index()
        levels = ['Street', 'Suburb', 'PostCode', 'Manual', 'Failed', 'Not geocoded']
        extra = sorted(set(ml.MatchLevel) - set(levels))
        st.altair_chart(alt.Chart(ml).mark_bar().encode(
            y=alt.Y("ProviderCategory:N", title=None),
            x=alt.X("Practices:Q", stack="normalize", title="Share of practices", axis=alt.Axis(format="%")),
            color=alt.Color("MatchLevel:N", title=None, legend=alt.Legend(orient="bottom"),
                            scale=alt.Scale(domain=levels + extra,
                                            range=["#1A7F5C", "#7DB89E", "#D68C1A", "#1F5F8B", "#BE3A34", "#8C969E"] + ['#8C969E'] * len(extra))),
            tooltip=["ProviderCategory", "MatchLevel", "Practices"]).properties(height=240), width="stretch")
    with right:
        st.subheader("Address issues")
        fl = (aq[aq.AddrQualityFlag != "0 OK"].groupby("AddrQualityFlag").Practices.sum()
              .reset_index().sort_values("AddrQualityFlag"))
        if fl.empty:
            st.success("No address issues in this selection.")
        else:
            fl["How to fix"] = fl.AddrQualityFlag.map(FLAG_FIX).fillna('Review source address and quality classification.')
            fl["Issue"] = fl.AddrQualityFlag.str[2:]
            st.dataframe(fl[["Issue", "Practices", "How to fix"]], hide_index=True, width="stretch")

    st.subheader("Data freshness")
    fr = src.provider_location_freshness()
    last = pd.to_datetime(fr.get("LastGeocode"))
    st.write(f"Last public-address geocode load: **{last:%d %b %Y}**" if pd.notna(last) else "No geocode timestamp supplied.")
    st.caption('Freshness shows stored public-address matching events. Counts cover all active practices; area estimates are not verified street locations.')
    st.write(f"{int(fr.get('Geocoded') or 0):,} of {int(fr.get('Practices') or 0):,} active practices have coordinates.")
    with st.expander('Practices needing attention and exports'):
        backlog = details[(~details.HasCoordinates) | (details.AddrQualityFlag != '0 OK')]
        st.caption(f'{len(backlog):,} records match the selected filters. Showing up to 200; the CSV includes every matching record.')
        st.dataframe(backlog.head(200), hide_index=True)
        st.download_button('Download address and coordinate backlog (CSV)', backlog.to_csv(index=False).encode(), 'provider_quality_backlog.csv', 'text/csv')
        st.download_button('Download quality summary (CSV)', aq.to_csv(index=False).encode(), 'provider_quality_summary.csv', 'text/csv')
        if st.button('Reload snapshot view' if getattr(src,'is_snapshot',False) is True else 'Refresh live quality data'):
            src.refresh()
            st.rerun()
