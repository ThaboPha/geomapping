"""Contracted specialists versus network hospitals: alignment, discipline gaps, recruitment targets."""
from __future__ import annotations

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

from ..data import get_source
from ..provider_alignment import ProviderAlignmentSource
from ..alignment_metrics import distance_summary
from .common import INK, MUTED, NETWORK, OK, RISK, WARN, deck

ORDER = ["On-site / adjacent", "Near (<= 5 km)", "Distant (> 5 km)",
         "No network hospital on shared options", "Not geocoded", "No mapped network hospital on selected option"]
COLORS = ["#1A7F5C", "#7DB89E", "#D68C1A", "#BE3A34", "#8C969E", "#8C969E"]
MAP_COLOR = {"On-site / adjacent": OK, "Near (<= 5 km)": [125, 184, 158], "Distant (> 5 km)": WARN,
             "No network hospital on shared options": RISK, "Not geocoded": MUTED}


def render():
    src = ProviderAlignmentSource(get_source())
    st.title("Specialists and network hospitals")
    st.caption("Are contracted specialists practising at or near the network hospitals members are sent to?")
    st.info('Live Databricks network relationships. Azure Maps address matches improve distance estimates but do not confirm admitting rights or on-site rooms. Locality points remain approximate.')

    al = src.alignment()
    if al.empty:
        st.warning("No alignment rows yet. Run Script 02 section 1 after geocoding.")
        return

    f1, f2 = st.columns(2)
    provinces = f1.multiselect("Provinces", sorted(al.ProvinceDescr.dropna().unique()), placeholder="All provinces")
    discs = f2.multiselect("Disciplines", sorted(al.PracTypeDescr.dropna().unique()), placeholder="All disciplines")
    if provinces:
        al = al[al.ProvinceDescr.isin(provinces)]
    if discs:
        al = al[al.PracTypeDescr.isin(discs)]

    counts = al.LocationAlignment.value_counts()
    summary = distance_summary(al)
    total = summary['assessed']
    c = st.columns(4)
    c[0].metric("Contracted specialists", f"{len(al):,}")
    c[1].metric("On-site at a network hospital", f"{100 * counts.get(ORDER[0], 0) / total:.0f}%" if total and (al.SpecialistMatchLevel.eq('Street') & al.HospMatchLevel.eq('Street')).any() else 'Not verified')
    c[2].metric("Within 5 km", f"{summary['within_pct']:.0f}%" if total else 'Not assessed')
    c[3].metric("More than 5 km away", f"{summary['above']:,}" if total else 'Not assessed',
                help="Count of assessed specialists more than 5 km from their nearest shared-option hospital. Distance does not establish admitting behaviour.")

    st.caption(f"{total:,} specialist-to-hospital distances estimated; {summary['unknown']:,} unresolved. Percentages use available distance pairs, including provisional locations; review location quality in the details.")

    by_disc = al.groupby(["PracTypeDescr", "LocationAlignment"]).size().rename("Specialists").reset_index()
    bar = alt.Chart(by_disc).mark_bar().encode(
        y=alt.Y("PracTypeDescr:N", title=None, sort="-x"),
        x=alt.X("Specialists:Q", stack="normalize", title="Share of contracted specialists",
                axis=alt.Axis(format="%")),
        color=alt.Color("LocationAlignment:N", title=None, sort=ORDER,
                        scale=alt.Scale(domain=ORDER, range=COLORS), legend=alt.Legend(orient="bottom", columns=3)),
        order=alt.Order("order:Q"),
        tooltip=["PracTypeDescr", "LocationAlignment", "Specialists"],
    ).transform_calculate(order=f"indexof({ORDER}, datum.LocationAlignment)")
    st.altair_chart(bar.properties(height=max(220, 26 * by_disc.PracTypeDescr.nunique())), width="stretch")

    st.subheader("Map")
    hosp = src.network_hospitals()
    if provinces:
        hosp = hosp[hosp.ProvinceDescr.isin(provinces)]
    pts = al.dropna(subset=["Latitude", "Longitude"]).copy()
    pts["color"] = pts.LocationAlignment.map(lambda value: MAP_COLOR.get(value,MUTED))
    pts["label"] = pts.PracName + " (" + pts.PracTypeDescr + ")"
    pts["detail"] = pts.LocationAlignment + ", " + pts.DistanceKm.astype(str) + " km to " + pts.HospName.fillna("-")
    hosp = hosp.dropna(subset=["Latitude", "Longitude"]).assign(label=hosp.PracName, detail="Network hospital")
    layers = [
        pdk.Layer("ScatterplotLayer", data=hosp, get_position="[Longitude, Latitude]", get_fill_color=NETWORK,
                  get_line_color=INK, stroked=True, get_radius=500, radius_min_pixels=6, pickable=True),
        pdk.Layer("ScatterplotLayer", data=pts, get_position="[Longitude, Latitude]", get_fill_color="color",
                  get_radius=150, radius_min_pixels=3, opacity=0.8, pickable=True),
    ]
    centre = pts if not pts.empty else hosp
    if centre.empty:
        st.info('No mapped specialist or hospital in this selection.')
    else:
        st.pydeck_chart(deck(layers, float(centre.Latitude.mean()), float(centre.Longitude.mean()),
                             5 if not provinces else 7,
                             tooltip={"html": "<b>{label}</b><br/>{detail}", "style": {"fontSize": "12px"}}),
                        height=420)
    st.caption("Blue: network hospitals. Dots: contracted specialists, coloured by alignment as in the chart.")

    st.subheader("Network hospitals missing a core discipline")
    gaps = src.hospital_gaps()
    if provinces:
        gaps = gaps[gaps.Province.isin(provinces)]
    missing = gaps[gaps.Assessment == 'No mapped specialist nearby']
    unknown = gaps[gaps.Assessment == 'Not assessed: missing coordinates']
    if missing.empty and unknown.empty:
        st.success('Each assessed network hospital has an address-level match for every core discipline nearby in this selection.')
    elif missing.empty:
        st.info('Missing or approximate coordinates prevent a complete core-discipline assessment.')
    else:
        wide = (missing.assign(gap="Missing").pivot_table(index=["Hospital", "Province"], columns="Discipline",
                                                          values="gap", aggfunc="first", fill_value="")
                .reset_index())
        wide.insert(2, "Disciplines missing", (wide.iloc[:, 2:] == "Missing").sum(axis=1))
        st.dataframe(wide.sort_values("Disciplines missing", ascending=False), hide_index=True, width="stretch")
        st.caption("No eligible contracted specialist address was found within 5 km on shared benefit options. "
                   "This is a network/address proximity gap; it does not establish hospital staffing, admitting rights or a confirmed clinical service gap.")

    if not unknown.empty:
        with st.expander('Hospital disciplines awaiting reliable address coordinates'):
            st.dataframe(unknown, hide_index=True)

    st.subheader("Recruitment targets")
    st.caption("Specialists not on the network whose rooms are at a network hospital (street-level match, "
               "within 500 m). Usually the quickest way to close a gap.")
    rec = src.recruitment_targets()
    if provinces:
        rec = rec[rec.ProvinceDescr.isin(provinces)]
    if discs:
        rec = rec[rec.PracTypeDescr.isin(discs)]
    if rec.empty:
        st.info("No verified street-level recruitment candidates are available for this selection. Area matches cannot establish on-site rooms.")
    else:
        show = rec.rename(columns={"PracNumDisplay": "Practice no.", "PracName": "Specialist",
                                   "PracTypeDescr": "Discipline", "ProvinceDescr": "Province",
                                   "NetworkHospital": "Network hospital", "DistanceKm": "Distance (km)"})
        st.dataframe(show, hide_index=True, width="stretch")
        st.download_button("Download recruitment list (CSV)", show.to_csv(index=False).encode(),
                           file_name="recruitment_targets.csv", mime="text/csv")

    with st.expander('Provider locations and alignment details'):
        st.dataframe(al[['PracNumDisplay','PracName','PracTypeDescr','ProvinceDescr','DisplayAddress','SpecialistMatchLevel','HospName','DistanceKm','LocationAlignment']],hide_index=True)
        st.download_button('Download specialist alignment (CSV)',al.to_csv(index=False).encode(),'specialist_alignment.csv','text/csv')
        st.dataframe(hosp[['PracNumDisplay','PracName','DisplayAddress','ProvinceDescr','MatchLevel']],hide_index=True)
        st.download_button('Download hospital directory (CSV)',hosp.to_csv(index=False).encode(),'network_hospitals.csv','text/csv')
        if st.button('Reload snapshot view' if getattr(src,'is_snapshot',False) is True else 'Refresh live alignment data'):
            src.refresh()
            st.rerun()
