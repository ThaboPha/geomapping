"""Find the nearest network providers for a member's option. Built for call centre agents."""
from __future__ import annotations

import hashlib
import pandas as pd
import pydeck as pdk
import streamlit as st

from ..data import get_source
from ..disciplines import provider_categories, discipline_label
from ..location import capture_location
from ..membership import require_member
from ..registered_location import show_registered_location
from ..place_search import search_places, search_provider_address
from ..geo import haversine_km
from .common import INK, NETWORK, OK, RISK, deck, standard_km, zoom_for_km, select_option

CATEGORY_LABEL = {"GP": "GP", "Core Specialist": "Specialist (core)", "Other Specialist": "Specialist (other)",
                  "Hospital": "Hospital", "Day Hospital": "Day hospital",
                  "Hospital-based Specialist": "Hospital-based specialist",
                  "Unclassified": "Other disciplines (unclassified)"}
TRAVEL_MODE = {'Driving': ('d', 'driving'), 'Public transport': ('r', 'transit'), 'Walking': ('w', 'walking')}


@st.dialog('Directions', width='large')
def _directions(loc, provider):
    st.write(f"{provider.PracName} · {provider.DisplayAddress}")
    st.caption(f'{provider.DistanceKm:.1f} km in a straight line. Confirm the practice premises; road distance and travel time can differ.')
    travel = st.segmented_control('Travel by', list(TRAVEL_MODE), default='Driving', key='dir_mode') or 'Driving'
    flag, mode = TRAVEL_MODE[travel]
    origin = f"{loc['lat']:.6f},{loc['lon']:.6f}"
    destination = f'{provider.Latitude:.6f},{provider.Longitude:.6f}'
    st.caption('Opening these directions shares the search and provider coordinates with Google Maps.')
    st.iframe(f'https://maps.google.com/maps?saddr={origin}&daddr={destination}&dirflg={flag}&output=embed', height=450)
    url = f'https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}&travelmode={mode}'
    st.link_button('Open in Google Maps', url)
    st.code(url, language=None)


def _location(src) -> dict | None:
    """Get a patient's chosen location, coordinates, and optional benefit option."""
    capture_location()
    member = require_member(src, optional=True)
    modes = (["Registered address"] if member else []) + ["Suburb or postcode", "Coordinates"]
    saved_mode = st.session_state.get('loc_mode', st.session_state.get('selected_location_mode'))
    if saved_mode not in modes:
        st.session_state['loc_mode'] = 'Registered address' if member else 'Suburb or postcode'
    how = st.segmented_control(
        "Or enter your location by",
        modes,
        default=None,
        key="loc_mode")
    st.session_state['selected_location_mode'] = how

    if how == 'Registered address':
        return show_registered_location(src, member)

    if how == "Suburb or postcode":
        st.session_state.setdefault('place_q', st.session_state.get('saved_place_query', ''))
        q = st.text_input("Suburb, town or postcode", placeholder="e.g. Soweto or 1804", key="place_q")
        st.session_state.saved_place_query = q
        st.caption('Place searches use real OpenStreetMap locations. Search text is sent to Photon or its Nominatim fallback; enter a suburb, town, postcode or street address without names or medical details.')
        if not q.strip():
            return None
        try:
            with st.spinner('Finding the location on the map…'):
                places = src.search_places(q) if getattr(src,'is_snapshot',False) is True else pd.DataFrame()
                if places.empty:
                    places = search_places(q)
        except Exception:
            st.error('The map location service is unavailable. Try again, or enter coordinates. No provider-derived location has been substituted.')
            return None
        if places.empty:
            st.error(f"No South African map location matches '{q}'. Add the town or province, or enter coordinates.")
            return None
        labels = places.Label.tolist()
        pick_key = 'place_pick_' + hashlib.sha256(q.strip().lower().encode()).hexdigest()[:12]
        picks = st.session_state.get('saved_place_picks', {})
        i = st.selectbox("Pick the location", range(len(labels)), index=min(picks.get(pick_key, 0), len(labels) - 1), format_func=lambda k: labels[k], key=pick_key)
        st.session_state.saved_place_picks = {**picks, pick_key: i}
        p = places.iloc[i]
        st.caption(f"Location source: {p.LocationSource}. A suburb search marks the area, not your house. Confirm the selected match.")
        return {"lat": float(p.Latitude), "lon": float(p.Longitude), "geotype": p.Geotype, "label": labels[i],
                'province': p.Province}

    if how == "Coordinates":
        saved = st.session_state.get('search_location') or {}
        st.session_state.setdefault("coord_lat", saved.get('lat') if st.session_state.get('selected_location_mode') == 'Coordinates' else None)
        st.session_state.setdefault("coord_lon", saved.get('lon') if st.session_state.get('selected_location_mode') == 'Coordinates' else None)
        c1, c2, c3 = st.columns(3)
        lat = c1.number_input("Latitude", value=None, format="%.5f", min_value=-35.0, max_value=-22.0, key="coord_lat")
        lon = c2.number_input("Longitude", value=None, format="%.5f", min_value=16.0, max_value=33.5, key="coord_lon")
        geo = c3.selectbox("Area type", ["Unknown", "Metro", "Urban", "Rural"], key="coord_geotype")
        if lat is None or lon is None:
            st.info("Enter both coordinates, or use your live location.")
            return None
        live = st.session_state.get('live_location')
        is_live = live and lat == live['lat'] and lon == live['lon']
        if is_live:
            if st.session_state.get('live_location_error'):
                st.info('Using your previously shared location.')
            else:
                st.success('Your location has populated the search coordinates.')
            st.caption(f"Device location accuracy: approximately {live['accuracy']:.0f} metres. Distances are straight-line estimates.")
            st.caption("This is your browser's estimated position. A laptop can return the wrong town even when its reported accuracy looks good. If the red dot is wrong, select Suburb or postcode and enter your actual area.")
            st.button("My location is wrong — search by suburb", key='correct_browser_location',
                      on_click=lambda: st.session_state.update(loc_mode='Suburb or postcode'))
            if live['accuracy'] > 1000:
                st.warning('Your device location is approximate. Check the map, or search by suburb for a better starting point.')
        label = ("your last shared location" if st.session_state.get('live_location_error') else "your current location") if is_live else f"{lat:.4f}, {lon:.4f}"
        return {"lat": lat, "lon": lon, "geotype": geo, "label": label,
                **({"accuracy": live['accuracy']} if is_live else {})}
    return None


def render():
    src = get_source()
    member = require_member(src, optional=True)
    st.title("Find a provider")
    st.caption("Choose your suburb or location, benefit option and type of care. Membership lookup is optional.")
    if src.mode == "databricks":
        st.caption("Provider locations may be approximate. Confirm your cover and the practice address before travelling.")
        snapshot=getattr(src,'is_snapshot',False) is True
        if st.button("Reload snapshot view" if snapshot else "Refresh live provider data", key="refresh_provider_data"):
            src.refresh()
            st.session_state['provider_refresh_time'] = pd.Timestamp.now(tz='Africa/Johannesburg').strftime('%H:%M:%S')
        if st.session_state.get('provider_refresh_time'):
            st.caption(f"View reloaded at {st.session_state['provider_refresh_time']} SAST. " + ('This reload does not update the snapshot.' if snapshot else 'Refresh reads the current GeoMap views.'))

    left, right = st.columns([1, 2], gap="large")
    with left:
        loc = _location(src)
        st.session_state['search_location'] = loc
        scope = st.radio("Provider directory", ["Selected option network", "All active providers"],
                         key='provider_scope', help="All active providers uses the full live provider view. Cover must be confirmed with your scheme.")
        all_providers = scope == 'All active providers'
        if all_providers:
            st.warning("Searching all active providers. Inclusion does not confirm cover on your benefit option.")

        opts = src.options()
        if opts.empty:
            st.warning("No current network product options are available in the data source.")
            return
        names = dict(zip(opts.ProdCode, opts.OptionName))
        if member and member['ProdCode'] not in names:
            st.warning("Your current benefit option has no network relationships in the connected GeoMap view. Confirm the source coverage with your scheme.")
        prod = select_option(src, member, key='lookup_option')
        if prod is None:
            return

        disciplines = src.disciplines()
        categories = provider_categories(disciplines)
        category = st.selectbox("Looking for", categories, index=categories.index("Hospital") if src.mode == "databricks" else 0,
                                format_func=lambda c: CATEGORY_LABEL.get(c, c))
        prac_type = None
        disc = disciplines[disciplines.ProviderCategory == category]
        if len(disc) > 1 or category in ("Core Specialist", "Other Specialist", "Hospital-based Specialist", "Unclassified"):
            choice = st.selectbox("Discipline", [None] + list(disc.PracType),
                                  format_func=lambda v: discipline_label(v, disc))
            prac_type = choice

        standards = src.standards()
        std = standard_km(standards, category, loc["geotype"]) if loc else None
        max_km = st.slider("Search up to (km)", 5, 200, int(min(200, max(20, (std or 25) * 2))), step=5)
        limit = st.number_input("Show at most", 5, 50, 10, step=5)
        include_unverified = False
        use_place_centroids = False
        if src.mode == "databricks":
            include_unverified = st.toggle(
                "Show providers with unverified referral eligibility", value=True, disabled=all_providers,
                help="These providers have current network relationships. Check with your medical scheme that you can use them on your option.")
            use_place_centroids = st.toggle(
                "Use approximate place locations for unmapped providers", value=False,
                help="Matches the provider's suburb/town, postcode and province to a provider-derived place centroid. This is an area location, not the practice address.")
        proposed = "StandardStatus" in standards and (standards.StandardStatus == "PROPOSED_NOT_APPROVED").any()
        if proposed:
            st.caption("Distance standards are proposed planning parameters awaiting Scheme approval.")

    with right:
        if not loc:
            st.markdown("#### Start with your location")
            st.write("Choose Use my live location, or enter your suburb or postcode, to search for providers near you.")
            return

        with st.spinner('Loading live providers and updating the map…'):
            res = src.providers_near(prod, loc["lat"], loc["lon"], category, prac_type, float(max_km), int(limit),
                                     include_unverified=include_unverified, use_place_centroids=use_place_centroids,
                                     all_providers=all_providers)
        pin_context = (prod, category, prac_type, all_providers, include_unverified)
        pin = st.session_state.get('provider_address_pin')
        if pin and pin['context'] == pin_context:
            row = dict(pin['record'])
            row['DistanceKm'] = float(haversine_km(loc['lat'], loc['lon'], row['Latitude'], row['Longitude']))
            if row['DistanceKm'] <= max_km:
                res = res[res.PracNumDisplay != row['PracNumDisplay']]
                res = pd.concat([res, pd.DataFrame([row])], ignore_index=True).sort_values('DistanceKm')
            else:
                st.info(f"The selected provider address is {row['DistanceKm']:.1f} km away, outside your {max_km} km radius. Widen the radius to show its blue marker.")
        label = CATEGORY_LABEL.get(category, category)
        what = label if category == "GP" else label.lower()

        if res.empty:
            if src.mode == "databricks" and not include_unverified and not all_providers:
                st.warning("No providers with confirmed assignment status match this search. Unknown statuses are excluded; "
                           "enable directory candidates to inspect current network relationships.")
            else:
                subject = f"active {what}" if all_providers else f"network {what} for {names.get(prod, prod)}"
                st.warning(f"No mapped {subject} within {max_km} km of {loc['label']}. "
                           "Widen the search or check coordinate coverage on the Data quality page.")
            nearest = None
        else:
            nearest = float(res.DistanceKm.iloc[0])
            unverified = all_providers or ("EligibilityStatus" in res and (res.EligibilityStatus == "Unverified assignment status").any())
            if unverified:
                st.warning(f"Nearest directory candidate: {nearest:.1f} km from {loc['label']}. "
                           "Check with your medical scheme that this provider is covered before booking.")
            elif proposed:
                st.info(f"Nearest network {what}: {nearest:.1f} km from {loc['label']}. "
                        "Access standards are proposed and cannot confirm approved access compliance.")
            elif std is None:
                st.success(f"Nearest network {what}: {nearest:.1f} km from {loc['label']}.")
            elif nearest <= std:
                st.success(f"Nearest network {what} is {nearest:.1f} km away, within the "
                           f"{std:.0f} km {loc['geotype'].lower()} standard.")
            else:
                st.warning(f"Nearest network {what} is {nearest:.1f} km away, beyond the "
                           f"{std:.0f} km {loc['geotype'].lower()} standard. Log as an access gap.")

        layers = []
        if std:
            layers.append(pdk.Layer("ScatterplotLayer", id="access-standard", data=pd.DataFrame([loc]), get_position="[lon, lat]",
                                    get_radius=std * 1000, filled=False, stroked=True,
                                    get_line_color=OK, line_width_min_pixels=1.5))
        member_pt = pd.DataFrame([{**loc, "PracName": loc["label"], "PracTypeDescr": "Your search location", "dist": 0}])
        if loc.get('accuracy', 0) > 0:
            layers.append(pdk.Layer("ScatterplotLayer", id="device-accuracy", data=member_pt,
                                    get_position="[lon, lat]", get_radius=float(loc['accuracy']),
                                    get_fill_color=RISK + [25], get_line_color=RISK + [100],
                                    stroked=True, line_width_min_pixels=1))
        layers.append(pdk.Layer("ScatterplotLayer", id="patient-location", data=member_pt,
                                get_position="[lon, lat]", get_fill_color=RISK, get_radius=60,
                                radius_min_pixels=7, pickable=True))
        layers.append(pdk.Layer("TextLayer", id="search-location-label", data=member_pt,
                                get_position="[lon, lat]", get_text="'Search location'",
                                get_color=INK, get_size=13, get_pixel_offset=[0, -20]))
        if not res.empty:
            pts = res.assign(dist=res.DistanceKm.round(1))
            layers.append(pdk.Layer("ScatterplotLayer", id="provider-locations", data=pts, get_position="[Longitude, Latitude]",
                                    get_fill_color=NETWORK, get_line_color=INK, stroked=True,
                                    line_width_min_pixels=2, get_radius=40, radius_min_pixels=9,
                                    pickable=True))
        # Keep the red search point visible over co-located blue provider markers.
        patient_layer = next(layer for layer in layers if layer.id == 'patient-location')
        layers.remove(patient_layer)
        layers.append(patient_layer)
        span = max(nearest or 0, float(res.DistanceKm.max()) if not res.empty else 0, std or 5,
                   float(loc.get('accuracy', 0)) / 1000)
        if st.button("Recenter map on my search location", key="recenter_search_map"):
            st.session_state['map_recenter_revision'] = st.session_state.get('map_recenter_revision', 0) + 1
        # A new widget identity resets the camera even when GPS returns the same point.
        # Streamlit only applies pydeck keys when selection handling is enabled.
        result_identity = res[['PracNumDisplay', 'Latitude', 'Longitude']].to_json() if not res.empty else 'empty'
        map_identity = f"{loc['lat']!r}:{loc['lon']!r}:{span}:{result_identity}:{st.session_state.get('location_revision', 0)}:{st.session_state.get('map_recenter_revision', 0)}"
        map_key = "provider_map_" + hashlib.sha256(map_identity.encode()).hexdigest()[:20]
        st.pydeck_chart(deck(layers, loc["lat"], loc["lon"], max(3, zoom_for_km(span) - 1),
                             tooltip={"html": "<b>{PracName}</b><br/>{PracTypeDescr}<br/>{dist} km",
                                      "style": {"fontSize": "12px"}}),
                        height=380, key=map_key, on_select="rerun",
                        alt="Provider map centred on your selected search location")
        st.caption(f"Map search point: {loc['lat']:.5f}, {loc['lon']:.5f}. "
                   "Red dot: your search location. Blue dots: providers." +
                   (" Pale red circle: your device's estimated accuracy." if loc.get('accuracy', 0) > 0 else ""))
        st.caption(f"Providers plotted in blue: {len(res)}. Address-only directory entries below have no map marker.")
        st.caption('Place search © OpenStreetMap contributors — https://www.openstreetmap.org/copyright')
        if std:
            st.caption(f"Red dot: search location. Green ring: {std:.0f} km "
                       + ("proposed planning radius." if proposed else "access standard."))

        if not res.empty:
            st.subheader(f"Providers shown on the map ({len(res)})")
            show = res.rename(columns={
                "PracNumDisplay": "Practice no.", "PracName": "Practice", "PracTypeDescr": "Discipline",
                "DisplayAddress": "Address", "DistanceKm": "Distance (km)", "Networks": "Network",
                "PracticeEmail": "Email", "MatchLevel": "Location accuracy", "EligibilityStatus": "Assignment status",
                "MapAddress": "Map address match"})
            show["Distance (km)"] = show["Distance (km)"].round(1)
            columns = ["Distance (km)", "Practice", "Practice no.", "Discipline", "Address",
                       "Network", "Email", "Location accuracy"]
            if "Assignment status" in show:
                columns.append("Assignment status")
            if 'Map address match' in show:
                columns.append('Map address match')
            st.dataframe(show[columns],
                         hide_index=True, width="stretch")
            if (res.MatchLevel != "Street").any():
                st.caption("Suburb, postcode and provisional place-centroid distances are approximate. "
                           "A place centroid identifies an area, not the provider's premises.")
            st.download_button("Download list (CSV)", show.to_csv(index=False).encode(),
                               file_name=f"network_{category.lower().replace(' ', '_')}_{prod}.csv",
                               mime="text/csv")
            direction_choice = st.selectbox('Directions to', range(len(res)), key='dir_pick',
                format_func=lambda index: f"{res.PracName.iloc[index]} ({res.DistanceKm.iloc[index]:.1f} km)")
            if st.button('Get directions', icon=':material/directions:'):
                _directions(loc, res.iloc[direction_choice])

        if src.mode == "databricks":
            st.subheader("Active provider directory awaiting coordinates" if all_providers else "Network directory awaiting provider coordinates")
            provinces = src.directory_provinces().ProvinceDescr.tolist()
            area = src.location_area(loc['lat'], loc['lon'])
            suggested = loc.get('province')
            if not suggested and not area.empty and float(area.iloc[0].DistanceKm) <= 75:
                suggested = area.iloc[0].Province
                st.caption(f"Search point is near {area.iloc[0].Place}, {suggested}. Confirm this is your area before using the directory.")
            province_choices = ["All provinces"] + provinces
            province_key = 'directory_province_' + hashlib.sha256(f"{loc['lat']}:{loc['lon']}".encode()).hexdigest()[:12]
            province = st.selectbox("Directory province", province_choices,
                index=province_choices.index(suggested) if suggested in provinces else 0, key=province_key,
                help="Filters provider addresses by province. Missing coordinates prevent distance filtering.")
            st.caption(("These are live active providers filtered by discipline and address province. " if all_providers else
                        "These are live network relationships filtered by option, discipline and provider address province. ") +
                       "Providers without coordinates cannot be ranked by distance. Confirm cover and the practice address before booking.")
            unmapped = src.unmapped_providers(prod, category, prac_type, int(limit), include_unverified,
                                             province=None if province == 'All provinces' else province,
                                             all_providers=all_providers)
            st.caption(f"Directory results: {province}.")
            if not unmapped.empty:
                directory = unmapped.rename(columns={"PracNumDisplay": "Practice no.", "PracName": "Practice",
                    "PracTypeDescr": "Discipline", "DisplayAddress": "Address", "ProvinceDescr": "Province",
                    "Networks": "Network", "LocationStatus": "Location status", "EligibilityStatus": "Assignment status"})
                st.dataframe(directory, hide_index=True, width="stretch")
                st.download_button("Download unmapped directory (CSV)", directory.to_csv(index=False).encode(),
                                   file_name=f"unmapped_network_{prod}.csv", mime="text/csv",
                                   key=f"directory_download_{prod}_{category}_{prac_type}_{province}_{include_unverified}_{all_providers}")
                st.markdown('#### Find a directory provider on the map')
                st.caption('These providers have no practice coordinates in Databricks. You can search their public practice address and confirm a map match. This does not verify cover or the premises.')
                provider_key = hashlib.sha256(str(pin_context).encode()).hexdigest()[:12]
                selected = st.selectbox('Provider address to locate', unmapped.PracNumDisplay.tolist(),
                    format_func=lambda number: unmapped.set_index('PracNumDisplay').at[number, 'PracName'],
                    key='provider_address_choice_' + provider_key)
                provider = unmapped[unmapped.PracNumDisplay == selected].iloc[0]
                address = str(provider.DisplayAddress or '').strip()
                st.write(address)
                lookup_key = str(pin_context) + ':' + str(selected) + ':' + address
                if st.button('Search this provider address', disabled=not address):
                    try:
                        matches = search_provider_address(provider.to_dict())
                        st.session_state['provider_address_matches'] = (lookup_key, matches)
                    except Exception:
                        st.session_state.pop('provider_address_matches', None)
                        st.error('Provider address lookup is unavailable. No coordinates were invented.')
                found = st.session_state.get('provider_address_matches')
                if found and found[0] == lookup_key:
                    matches = found[1]
                    if matches.empty:
                        st.warning('No map match was found for this provider address. Confirm the address with the practice.')
                    else:
                        choice = st.selectbox('Confirm provider map address', range(len(matches)),
                            format_func=lambda index: matches.iloc[index].Label,
                            key='provider_match_' + hashlib.sha256(lookup_key.encode()).hexdigest()[:12])
                        if st.button('Show this provider in blue'):
                            match = matches.iloc[choice]
                            record = provider.to_dict()
                            record.update(Latitude=float(match.Latitude), Longitude=float(match.Longitude),
                                MatchLevel='Address search match; confirm premises', PracticeEmail=None,
                                MapAddress=match.Label)
                            st.session_state['provider_address_pin'] = dict(context=pin_context, record=record)
                            st.rerun()
            else:
                st.info("No providers awaiting coordinates match the selected directory filters. Try another province, discipline or benefit option.")
