"""Member access coverage and the radius proposal (what-if on the access standards)."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from ..data import get_source


GEOTYPES = ["Metro", "Urban", "Rural"]
CATS = {"GP": "GP", "Core Specialist": "Core specialists", "Other Specialist": "Other specialists",
        "Hospital": "Network hospital"}


def _within(df: pd.DataFrame, radius: float) -> int:
    return int(df.loc[df.KmBin <= radius, "Members"].sum())


def _curve(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for g, d in df.groupby("Geotype"):
        total = d.Members.sum()
        counts = d[d.KmBin <= 200].groupby("KmBin").Members.sum().reindex(range(0, 201), fill_value=0).cumsum()
        rows.append(pd.DataFrame({"Geotype": g, "Km": counts.index, "Pct": 100 * counts.to_numpy() / total}))
    return pd.concat(rows) if rows else pd.DataFrame(columns=["Geotype", "Km", "Pct"])


def render():
    src = get_source()
    st.title("Member access and radius proposal")
    st.caption("How far members live from the nearest network provider on their own option. "
               "Move the radius sliders to test a standard before proposing it to the Scheme.")

    columns = ['ProdCode', 'Geotype', 'Province', 'District', 'ProviderCategory', 'Discipline', 'KmBin', 'Members']
    st.caption('Area rule: inside a metro or less than 10 km from its boundary = Metro; 10 to less than 40 km = Urban; 40 km or more = Rural. Distances are straight-line estimates. The sliders below change provider-access radii, not these area classification bands.')
    planning = st.toggle('Use available area coordinates for planning', value=False, key='member_area_planning')
    if planning:
        st.warning('Planning estimates use current product-linked providers and available area coordinates. Product links do not confirm network cover. Percentages use located members and mapped providers; unmapped providers may reduce the reported gaps.')
    try:
        hist = src.access_histogram(planning=True) if planning else src.access_histogram()
    except Exception as exc:
        if 'TABLE_OR_VIEW_NOT_FOUND' not in str(exc):
            st.error('Member coverage data could not be read. Try refreshing the live data.')
            return
        hist = pd.DataFrame(columns=columns)
    assessed = not hist.empty
    readiness = pd.DataFrame()
    try:
        result = src.member_assessment_summary(planning=True) if planning else src.member_assessment_summary()
        if isinstance(result, pd.DataFrame):
            readiness = result
    except Exception as exc:
        if not any(code in str(exc) for code in ['TABLE_OR_VIEW_NOT_FOUND', 'UNRESOLVED_COLUMN']):
            st.error('Member coverage readiness could not be read. Please refresh and try again.')
    distribution = pd.DataFrame()
    if not assessed:
        try:
            distribution = src.member_distribution()
        except Exception:
            st.error('Current membership_live distribution could not be read. Please refresh and try again.')
    if not assessed:
        st.info('Member counts come from current active membership_live beneficiaries. The location pipeline tracks geocoding and classification readiness; outside counts and coverage percentages remain blank for unassessed members.')

    opts = src.options()
    names = dict(zip(opts.ProdCode, opts.OptionName))
    standards = src.standards()
    available_codes = sorted(set(opts.ProdCode.tolist()) | set(distribution.ProdCode.tolist() if not distribution.empty else []) | set(readiness.ProdCode.tolist() if not readiness.empty else []))

    f1, f2, f3 = st.columns([1.2, 1.2, 1])
    category = f1.selectbox("Provider type", list(CATS), format_func=CATS.get)
    sub = hist[hist.ProviderCategory == category]
    discs = sorted(sub.Discipline.dropna().unique())
    if sub.empty:
        disciplines = src.disciplines()
        discs = sorted(disciplines.loc[disciplines.ProviderCategory == category, 'PracTypeDescr'].dropna().unique())
    if len(discs) > 1:
        disc = f2.selectbox("Discipline", discs)
        sub = sub[sub.Discipline == disc]
    else:
        f2.text_input("Discipline", discs[0] if discs else "", disabled=True)
    chosen = f3.multiselect("Options", available_codes, format_func=lambda c: names.get(c, c),
                            placeholder="All options")
    if chosen:
        sub = sub[sub.ProdCode.isin(chosen)]
    loc = st.session_state.get('search_location') or {}
    if loc:
        st.caption(f"Find a provider location: {loc['label']}. Member percentages use the selected population filters, not all members placed at this suburb.")
    provinces = st.multiselect("Provinces", sorted(sub.Province.dropna().unique()) if assessed else src.directory_provinces().ProvinceDescr.dropna().tolist(), placeholder="All provinces")
    if provinces:
        sub = sub[sub.Province.isin(provinces)]

    if not distribution.empty:
        if chosen:
            distribution = distribution[distribution.ProdCode.isin(chosen)]
        if provinces:
            distribution = distribution[distribution.Province.isin(provinces)]
    selected_readiness = pd.DataFrame()
    if not readiness.empty:
        selected_readiness = readiness[readiness.ProviderCategory == category]
        if len(discs) > 1:
            selected_readiness = selected_readiness[selected_readiness.Discipline == disc]
        if chosen:
            selected_readiness = selected_readiness[selected_readiness.ProdCode.isin(chosen)]
        if provinces:
            selected_readiness = selected_readiness[selected_readiness.Province.isin(provinces)]
    st.subheader("Test a standard")
    radius, target = {}, {}
    cols = st.columns(3)
    for col, g in zip(cols, GEOTYPES):
        row = standards[(standards.ProviderCategory == category) & (standards.Geotype == g)]
        default = int(row.RadiusKm.iloc[0]) if not row.empty else 25
        target[g] = float(row.TargetCoveragePct.iloc[0]) if not row.empty else 85.0
        radius[g] = col.slider(f"{g} radius (km)", 1, 200, default, key=f"r_{category}_{g}")

    cols = st.columns(3)
    for col, g in zip(cols, GEOTYPES):
        d = sub[sub.Geotype == g]
        total = int(d.Members.sum())
        if total == 0:
            col.metric(f"{g} members within {radius[g]} km", "No assessed members")
            continue
        pct = 100 * _within(d, radius[g]) / total
        col.metric(f"{g} members within {radius[g]} km", f"{pct:.1f}%",
                   delta=f"{pct - target[g]:+.1f} pts vs {target[g]:.0f}% target",
                   delta_color="normal")
        none = int(d.loc[d.KmBin == 999, "Members"].sum())
        col.caption(f"{total - _within(d, radius[g]):,} of {total:,} members outside"
                    + (f"; {none:,} have no mapped provider in this directory" if none else ""))

    curve = _curve(sub)
    rules = pd.DataFrame({"Geotype": GEOTYPES, "Km": [radius[g] for g in GEOTYPES]})
    color = alt.Color("Geotype:N", scale=alt.Scale(domain=GEOTYPES, range=["#1F5F8B", "#D68C1A", "#1A7F5C"]))
    chart = (alt.Chart(curve).mark_line().encode(
                x=alt.X("Km:Q", title="Distance to nearest network provider (km)"),
                y=alt.Y("Pct:Q", title="% of members within distance", scale=alt.Scale(domain=[0, 100])),
                color=color, tooltip=[alt.Tooltip("Geotype:N"), alt.Tooltip("Km:Q"), alt.Tooltip("Pct:Q", format=".1f")])
             + alt.Chart(rules).mark_rule(strokeDash=[4, 3]).encode(x="Km:Q", color=color))
    st.altair_chart(chart.properties(height=320), width="stretch")
    st.caption("Where a line flattens, extra distance adds few members: a natural place to set the standard. "
               "Dashed lines are the radii above.")

    st.subheader("By option")
    rows = []
    for (prod, g), d in sub.groupby(["ProdCode", "Geotype"]):
        total = d.Members.sum()
        rows.append({"Option": names.get(prod, prod), "Area": g, "Members": int(total),
                     "Within standard %": round(100 * _within(d, radius[g]) / total, 1),
                     "Target %": target[g]})
    by_opt = pd.DataFrame(rows, columns=["Option", "Area", "Members", "Within standard %", "Target %"])
    if sub.empty:
        if not selected_readiness.empty:
            totals = selected_readiness.groupby(['ProdCode','Geotype']).Members.sum()
            by_opt = pd.DataFrame([{'Option': names.get(prod, prod), 'Area': area,
                'Members': int(count), 'Within standard %': None, 'Target %': None,
                '% of selected members': round(100 * count / totals.sum(), 1)}
                for (prod, area), count in totals.items()])
        elif not distribution.empty:
            totals = distribution.groupby('ProdCode').Members.sum()
            by_opt = pd.DataFrame([{'Option': names.get(prod, prod), 'Area': 'Unclassified',
                'Members': int(count), 'Within standard %': None, 'Target %': None,
                '% of selected members': round(100 * count / totals.sum(), 1)} for prod, count in totals.items()])
        else:
            by_opt = pd.DataFrame(columns=['Option', 'Area', 'Members', 'Within standard %', 'Target %'])
    if not by_opt.empty:
        st.dataframe(by_opt.style.apply(
            lambda r: ["color: #BE3A34" if pd.notna(r["Within standard %"]) and r["Within standard %"] < r["Target %"] else "" for _ in r], axis=1),
            hide_index=True, width="stretch")

    if by_opt.empty:
        st.dataframe(by_opt, hide_index=True, width="stretch")

    st.subheader("Where the gaps are")
    gaps = []
    for (prov, dist, g), d in sub.groupby(["Province", "District", "Geotype"]):
        outside = int(d.Members.sum() - _within(d, radius[g]))
        if outside:
            gaps.append({"Province": prov, "District": dist, "Area": g, "Members outside": outside,
                         "Members": int(d.Members.sum())})
    gaps = pd.DataFrame(gaps, columns=["Province", "District", "Area", "Members outside", "Members"])
    if gaps.empty and assessed and not sub.empty:
        st.success("Every member in this selection is within the tested standard.")
    elif not gaps.empty:
        gaps["% outside"] = (100 * gaps["Members outside"] / gaps["Members"]).round(1)
        st.dataframe(gaps.sort_values("Members outside", ascending=False).head(25), hide_index=True, width="stretch")

    if gaps.empty:
        display_gaps = pd.DataFrame(columns=['Province', 'District', 'Area', 'Members outside', 'Members', '% outside'])
        if not selected_readiness.empty:
            display_gaps = pd.DataFrame([dict(Province=province, District=district, Area=area,
                **{'Members outside': None, 'Members': int(count), '% outside': None})
                for (province, district, area), count in selected_readiness.groupby(['Province','District','Geotype']).Members.sum().items()])
        elif not distribution.empty:
            display_gaps = pd.DataFrame([dict(Province=province, District='Unknown', Area='Unclassified',
                **{'Members outside': None, 'Members': int(count), '% outside': None})
                for province, count in distribution.groupby('Province').Members.sum().items()])
        st.dataframe(display_gaps, hide_index=True, width='stretch')
        if not assessed:
            st.caption('Geography comes from available coordinates and explicit boundary classifications. Unknown locations and area types are retained. Blank outside values mean unassessed, not zero.')
        gaps = display_gaps
    if not distribution.empty:
        st.subheader('Member distribution by plan and registered locality')
        locality = distribution.groupby(['ProdCode', 'Province', 'Locality'], dropna=False).Members.sum().reset_index()
        locality['% of plan members'] = (100 * locality.Members / locality.groupby('ProdCode').Members.transform('sum')).round(1)
        locality['Option'] = locality.ProdCode.map(lambda code: names.get(code, code))
        st.dataframe(locality[['Option', 'Province', 'Locality', 'Members', '% of plan members']], hide_index=True)
        st.caption('Locality is the registered town, not an official district. Postal addresses and account-address fallbacks are included; these counts do not establish where members live or whether access standards are met.')
        st.download_button('Download member distribution (CSV)', locality.to_csv(index=False).encode(), 'member_distribution.csv', 'text/csv')
    st.download_button('Download by option (CSV)', by_opt.to_csv(index=False).encode(), 'member_access_by_option.csv', 'text/csv')
    st.download_button('Download member gaps (CSV)', gaps.reindex(columns=['Province', 'District', 'Area', 'Members outside', 'Members', '% outside']).to_csv(index=False).encode(), 'member_access_gaps.csv', 'text/csv')

    proposal = pd.DataFrame([{"ProviderCategory": category, "Geotype": g, "RadiusKm": radius[g],
                              "TargetCoveragePct": target[g],
                              "CoveragePctAtRadius": round(100 * _within(sub[sub.Geotype == g], radius[g])
                                                           / max(1, sub[sub.Geotype == g].Members.sum()), 1) if sub[sub.Geotype == g].Members.sum() else None}
                             for g in GEOTYPES])
    st.download_button("Export this standard (CSV)", proposal.to_csv(index=False).encode(),
                       file_name=f"proposed_standard_{category.lower().replace(' ', '_')}.csv", mime="text/csv",
                       help="Load into GeoMap.AccessStandard once the Scheme signs it off.")
