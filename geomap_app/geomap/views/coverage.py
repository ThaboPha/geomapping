"""Member access coverage and the radius proposal (what-if on the access standards)."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st
import pydeck as pdk

from ..data import get_source
from ..membership import require_member
from ..geo import haversine_km
from ..place_search import search_provider_address
from .common import zoom_for_km, select_option

GEOTYPES = ["Metro", "Urban", "Rural"]
CATS = {"GP": "GP", "Core Specialist": "Core specialists", "Other Specialist": "Other specialists",
        "Hospital": "Network hospital"}


def render():
    from .member_population import render as render_members
    render_members()
    with st.expander('Provider availability from Find a provider location', expanded=False):
        render_population()
    with st.expander('Provider directory from selected location', expanded=False):
        render_personal()


def render_personal():
    src = get_source()
    member = require_member(src, optional=True)
    if member:
        st.caption(f"Current benefit option: {member['ProdCode']}")
    prod = select_option(src, member, key='access_option')
    if prod is None:
        return
    st.write("Explore access from your selected location using live provider network relationships.")
    loc = st.session_state.get('search_location')
    if not loc:
        st.info("Choose your live location or enter an address on Find a provider first. Membership records do not provide verified map coordinates.")
        return
    st.caption(f"Search location: {loc['label']} ({loc['lat']:.5f}, {loc['lon']:.5f})")
    category = st.selectbox("Provider type", list(CATS), format_func=CATS.get, key='personal_category')
    all_providers = st.radio('Provider directory', ['Selected option network', 'All active providers'],
        key='personal_directory_scope') == 'All active providers'
    network = src.network_directory(prod)
    network_count = int(network.ProviderCategory.eq(category).sum())
    if all_providers:
        st.warning('All active provider directory: cover under your option is not confirmed. Check with your scheme before booking.')
    elif network_count == 0:
        st.info(f"The live GeoMap views list no {CATS[category]} network practices for option {prod}. A larger radius cannot add network relationships. Select All active providers to search the live directory; cover is not confirmed.")
    prac_type = None
    if category in ('Core Specialist', 'Other Specialist'):
        disciplines = src.disciplines()
        choices = disciplines[disciplines.ProviderCategory == category]
        prac_type = st.selectbox('Discipline', [None] + choices.PracType.tolist(),
            format_func=lambda code: 'Any discipline' if code is None else choices.set_index('PracType').at[code, 'PracTypeDescr'], key='personal_discipline')
    radius = st.slider("Search radius (km)", 5, 200, 50, step=5)
    include_unknown = st.toggle("Include unverified referral eligibility", value=True)
    provinces = sorted(src.network_directory(prod).ProvinceDescr.dropna().unique())
    province = st.selectbox('Directory province', ['All provinces'] + provinces,
        key='personal_directory_province', help='Address filter only. Providers without coordinates cannot be filtered by radius.')
    st.caption("Network membership does not confirm individual cover or referral eligibility. Distances are straight-line estimates; this radius is your search choice.")
    with st.spinner("Reading your option's live network…"):
        mapped = src.providers_near(prod, loc['lat'], loc['lon'], category,
                                    prac_type, radius, 50, include_unverified=include_unknown, all_providers=all_providers)
        missing = src.unmapped_providers(prod, category, prac_type, 100,
                                        include_unverified=include_unknown, province=None if province == 'All provinces' else province, all_providers=all_providers)
    preview = None
    pin = st.session_state.get('provider_address_pin')
    if pin:
        record = pin['record']
        network = src.network_directory(prod)
        allowed = network[(network.PracNumDisplay == record['PracNumDisplay']) & (network.ProviderCategory == category)]
        if prac_type is not None:
            allowed = allowed[allowed.PracType == prac_type]
        allowed = allowed[(allowed.AssBlockActive == 0) | (include_unknown & allowed.AssBlockActive.isna())]
        distance = float(haversine_km(loc['lat'], loc['lon'], record['Latitude'], record['Longitude']))
        if not allowed.empty:
            preview = record
            if distance > radius:
                st.info(f'Confirmed address match is {distance:.1f} km away, outside your radius. Its blue marker is shown for reference; it is not a nearby result.')
        if not allowed.empty and distance <= radius:
            record = {**record, 'DistanceKm': distance}
            mapped = pd.concat([mapped[mapped.PracNumDisplay != record['PracNumDisplay']], pd.DataFrame([record])], ignore_index=True).sort_values('DistanceKm').head(50)
            st.caption('Includes the provider address match you confirmed on Find a provider. Confirm the premises; this is not a verified source geocode.')
    st.metric("Mapped active providers within your radius (up to 50)" if all_providers else "Mapped network results within your radius (up to 50)", 'Not assessed' if mapped.empty and not missing.empty else len(mapped))
    if mapped.empty:
        if not missing.empty:
            st.warning("Distance access cannot be assessed for providers without coordinates. Your live directory appears below; increasing the radius cannot locate these practices.")
        elif all_providers or network_count:
            st.info(f'No mapped providers match your filters within {radius} km. Try another provider type or a wider search.')
    else:
        st.dataframe(mapped[['PracName', 'PracTypeDescr', 'DisplayAddress', 'DistanceKm', 'MatchLevel', 'EligibilityStatus']], hide_index=True)
        st.download_button('Download member access results (CSV)', mapped.to_csv(index=False).encode(), 'member_access_results.csv', 'text/csv')
    if not missing.empty:
        st.subheader("Active provider directory awaiting coordinates" if all_providers else "Network directory awaiting provider coordinates")
        st.caption("Up to 100 live records for your selected directory and filters. These are not confirmed nearby results. Search a public practice address below to confirm a map match.")
        st.dataframe(missing[['PracName', 'PracTypeDescr', 'DisplayAddress', 'ProvinceDescr', 'EligibilityStatus']], hide_index=True)
        st.download_button('Download member network directory (CSV)', missing.to_csv(index=False).encode(), 'member_network_directory.csv', 'text/csv')
        selected = st.selectbox('Provider address to locate', missing.PracNumDisplay.tolist(),
            format_func=lambda number: missing.set_index('PracNumDisplay').at[number, 'PracName'], key='personal_provider_address')
        provider = missing[missing.PracNumDisplay == selected].iloc[0]
        st.write(provider.DisplayAddress)
        lookup_key = (prod, selected, str(provider.DisplayAddress))
        if st.button('Search this provider address', key='personal_address_search'):
            try:
                st.session_state['personal_address_matches'] = (lookup_key, search_provider_address(provider.to_dict()))
            except Exception:
                st.session_state.pop('personal_address_matches', None)
                st.error('Public address search is unavailable. Please try again.')
        found = st.session_state.get('personal_address_matches')
        if found and found[0] == lookup_key:
            matches = found[1]
            if matches.empty:
                st.info('No public map match found. Confirm the address with the practice.')
            else:
                choice = st.selectbox('Confirm provider map address', range(len(matches)),
                    format_func=lambda index: matches.iloc[index].Label, key='personal_address_match')
                if st.button('Show this provider in blue', key='personal_address_confirm'):
                    match = matches.iloc[choice]
                    record = provider.to_dict()
                    record.update(Latitude=float(match.Latitude), Longitude=float(match.Longitude),
                        MatchLevel='Address search match; confirm premises', PracticeEmail=None, MapAddress=match.Label)
                    st.session_state['provider_address_pin'] = dict(context=lookup_key, record=record)
                    st.rerun()
    if not mapped.empty or preview:
        points = mapped[['Latitude', 'Longitude', 'PracName']].copy() if not mapped.empty else pd.DataFrame([preview])[['Latitude', 'Longitude', 'PracName']]
        points['color'] = [[31, 95, 139]] * len(points)
        points = pd.concat([points, pd.DataFrame([{'Latitude': loc['lat'], 'Longitude': loc['lon'],
            'PracName': 'Your search location', 'color': [190, 58, 52]}])], ignore_index=True)
        span = float(haversine_km(points.Latitude.min(), points.Longitude.min(), points.Latitude.max(), points.Longitude.max()))
        st.pydeck_chart(pdk.Deck(layers=[pdk.Layer('ScatterplotLayer', points,
            get_position='[Longitude, Latitude]', get_fill_color='color', get_radius=120,
            radius_min_pixels=7, pickable=True)],
            initial_view_state=pdk.ViewState(latitude=float(points.Latitude.mean()),
                longitude=float((points.Longitude.min() + points.Longitude.max()) / 2), zoom=max(3, zoom_for_km(span) - 1)),
            tooltip={'text': '{PracName}'}, map_style='light'), key='personal_access_map')


def _within(df: pd.DataFrame, radius: float) -> int:
    return int(df.loc[df.KmBin <= radius, "Members"].sum())


def _curve(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for g, d in df.groupby("Geotype"):
        total = d.Members.sum()
        counts = d[d.KmBin <= 200].groupby("KmBin").Members.sum().reindex(range(0, 201), fill_value=0).cumsum()
        rows.append(pd.DataFrame({"Geotype": g, "Km": counts.index, "Pct": 100 * counts.to_numpy() / total}))
    return pd.concat(rows) if rows else pd.DataFrame(columns=["Geotype", "Km", "Pct"])


def render_population():
    from ..location_standards import assess_option
    from ..session_geocodes import SessionNetworkSource

    src = get_source()
    st.subheader("Test a standard from your selected location")
    loc = st.session_state.get('search_location')
    if not loc:
        st.info("Select a suburb, coordinates or live location on Find a provider first.")
        st.write('Open Find a provider using the sidebar, then return here.')
        return
    st.caption(f"Search location: {loc['label']} ({loc['lat']:.5f}, {loc['lon']:.5f})")
    st.caption("Tests provider availability from this location. Each area radius is a planning scenario for the same location; results are not population coverage percentages.")
    opts = src.options()
    names = dict(zip(opts.ProdCode, opts.OptionName))
    if opts.empty:
        st.info('No network options available.')
        return
    f1, f2 = st.columns(2)
    category = f1.selectbox('Provider type', list(CATS) + ['Day Hospital'],
        format_func=lambda code: CATS.get(code, 'Day hospital'), key='planning_category')
    disciplines = src.disciplines()
    choices = disciplines[disciplines.ProviderCategory == category]
    prac_type = f2.selectbox('Discipline', [None] + choices.PracType.tolist(),
        format_func=lambda code: 'All disciplines' if code is None else choices.set_index('PracType').at[code, 'PracTypeDescr'],
        disabled=choices.empty, key='planning_discipline_' + category)
    codes = opts.ProdCode.tolist()
    saved = st.session_state.get('selected_benefit_option')
    chosen = st.multiselect('Options', codes, default=[saved] if saved in codes else [],
        format_func=lambda code: names.get(code, code), placeholder='All options', key='planning_options')
    chosen = chosen or codes
    provinces = st.multiselect('Provinces', src.directory_provinces().ProvinceDescr.dropna().tolist(), placeholder='All provinces', key='planning_provinces')
    approximate = st.toggle('Use approximate provider suburb locations', value=False, key='planning_approximate',
        help='Use source place centroids for unmapped providers. These are suburb estimates, not verified practice positions.')
    if approximate:
        st.caption('Approximate suburb distances are provisional. Confirm practice addresses before relying on a gap or access result.')
    standards = src.standards()
    radii = {}
    for col, area in zip(st.columns(3), GEOTYPES):
        rows = standards[(standards.ProviderCategory == ('Hospital' if category == 'Day Hospital' else category)) & (standards.Geotype == area)]
        default = int(rows.RadiusKm.iloc[0]) if not rows.empty else 25
        radii[area] = col.slider(f'{area} radius (km)', 1, 200, max(1, min(200, default)), key=f'local_r_{category}_{area}')
    area = st.selectbox('Area standard to apply', GEOTYPES,
        index=GEOTYPES.index(loc.get('geotype')) if loc.get('geotype') in GEOTYPES else 0, key='planning_area')
    st.caption('Choose the applicable area classification for this suburb. Standards are proposed planning parameters.')
    matches = dict(st.session_state.get('alignment_confirmed_locations', {}))
    pin = st.session_state.get('provider_address_pin')
    if pin:
        record = pin['record']
        matches[record['PracNumDisplay']] = dict(SourceAddress=record['DisplayAddress'],
            Latitude=record['Latitude'], Longitude=record['Longitude'])
    network_source = SessionNetworkSource(src, matches)
    summaries, details, curves, scenarios = [], [], [], []
    with st.spinner('Testing selected networks from your location?'):
        for prod in chosen:
            directory = network_source.network_directory(prod)
            directory = directory[directory.ProviderCategory == category].copy()
            if prac_type is not None:
                directory = directory[directory.PracType == prac_type]
            if provinces:
                directory = directory[directory.ProvinceDescr.isin(provinces)]
            directory = directory[(directory.AssBlockActive == 0) | directory.AssBlockActive.isna()]
            if approximate and not directory.empty:
                estimates = src.providers_near(prod, loc['lat'], loc['lon'], category, prac_type, 200, len(directory) + 1,
                    include_unverified=True, use_place_centroids=True)
                for row in estimates.itertuples():
                    mask = (directory.PracNumDisplay == row.PracNumDisplay) & (directory.Latitude.isna() | directory.Longitude.isna())
                    directory.loc[mask, ['Latitude', 'Longitude', 'MatchLevel']] = [row.Latitude, row.Longitude, row.MatchLevel]
            assessed, summary = assess_option(directory, loc, radii[area])
            summaries.append(dict(Option=names.get(prod, prod), ProdCode=prod, RadiusKm=radii[area], **summary))
            assessed['Option'] = names.get(prod, prod)
            details.append(assessed)
            for scenario in GEOTYPES:
                _, result = assess_option(directory, loc, radii[scenario])
                scenarios.append(dict(Option=names.get(prod, prod), Area=scenario, RadiusKm=radii[scenario], **result))
            for km in range(201):
                curves.append(dict(Option=names.get(prod, prod), Km=km,
                    Providers=int(assessed.DistanceKm.le(km).sum())))
    summary = pd.DataFrame(summaries)
    scenario_frame = pd.DataFrame(scenarios)
    for col, scenario in zip(st.columns(3), GEOTYPES):
        results = scenario_frame[scenario_frame.Area == scenario]
        col.metric(f'Options with a provider within {radii[scenario]} km ({scenario})', f"{int(results.Nearby.gt(0).sum())} / {len(results)}")
    st.altair_chart(alt.Chart(pd.DataFrame(curves)).mark_line().encode(
        x=alt.X('Km:Q', title='Distance from selected location (km)', scale=alt.Scale(domain=[0, 200])),
        y=alt.Y('Providers:Q', title='Mapped network providers within distance'),
        color='Option:N', tooltip=['Option', 'Km', 'Providers']).properties(height=300), width='stretch')
    st.subheader('By option')
    st.dataframe(summary, hide_index=True)
    st.subheader('Where the gaps are')
    gaps = summary[summary.Nearby == 0].copy()
    if gaps.empty:
        st.success('Every selected option has a mapped provider within the tested radius at this location.')
    else:
        gaps.insert(0, 'Location', loc['label'])
        st.dataframe(gaps, hide_index=True)
        st.caption('Missing provider locations make a gap unresolved. No listed network providers identifies a directory gap; mapped providers beyond the radius identify a distance gap among the available records.')
    st.subheader('Provider distances and missing locations')
    providers = pd.concat(details, ignore_index=True)
    columns = ['Option', 'PracNumDisplay', 'PracName', 'PracTypeDescr', 'DisplayAddress', 'ProvinceDescr', 'DistanceKm', 'WithinStandard', 'MatchLevel', 'EligibilityStatus']
    st.dataframe(providers.reindex(columns=columns).sort_values('DistanceKm'), hide_index=True)
    st.caption('Network relationships with unknown assignment status are included. Confirm cover and referral eligibility separately.')
    export = scenario_frame.assign(Location=loc['label'], Latitude=loc['lat'], Longitude=loc['lon'],
        ProviderCategory=category, Discipline='All disciplines' if prac_type is None else str(prac_type),
        StandardStatus='Proposed; not approved')
    st.download_button('Export this standard (CSV)', export.to_csv(index=False).encode(), 'location_standard.csv', 'text/csv')
    st.download_button('Download gaps (CSV)', gaps.to_csv(index=False).encode(), 'location_gaps.csv', 'text/csv')
    st.download_button('Download provider distances (CSV)', providers.reindex(columns=columns).to_csv(index=False).encode(), 'location_provider_distances.csv', 'text/csv')
