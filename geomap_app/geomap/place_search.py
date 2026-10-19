"""Real OpenStreetMap place lookup; never derive patient locations from provider coordinates."""
import json
import math
import os
import time
from threading import Lock
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st

ENDPOINT = os.getenv('GEOMAP_GEOCODER_URL', 'https://photon.komoot.io/api/')
COLUMNS = ['Place', 'Town', 'PostCode', 'Province', 'Geotype', 'Latitude', 'Longitude', 'Label', 'LocationSource']
_FALLBACK_LOCK = Lock()
_LAST_FALLBACK = 0.0


def parse_places(payload):
    rows = []
    for feature in payload.get('features', []):
        props = feature.get('properties', {})
        coords = feature.get('geometry', {}).get('coordinates', [])
        if str(props.get('countrycode') or '').upper() != 'ZA' or len(coords) < 2:
            continue
        try:
            lon, lat = map(float, coords[:2])
        except (ValueError, TypeError):
            continue
        if not (math.isfinite(lat) and math.isfinite(lon) and -35 <= lat <= -22 and 16 <= lon <= 33.5):
            continue
        place = props.get('name') or props.get('street') or props.get('city') or props.get('postcode')
        if not place:
            continue
        label = ', '.join(dict.fromkeys(str(v) for v in [
            props.get('housenumber'), props.get('street'), place, props.get('district'),
            props.get('city'), props.get('state'), props.get('postcode')] if v))
        rows.append(dict(Place=place, Town=props.get('city', ''), PostCode=props.get('postcode', ''),
            Province=props.get('state', ''), Geotype='Unknown', Latitude=lat, Longitude=lon,
            Label=label, LocationSource='OpenStreetMap / Photon'))
    return pd.DataFrame(rows, columns=COLUMNS).drop_duplicates(subset=['Label', 'Latitude', 'Longitude'])


@st.cache_data(ttl=3600, max_entries=200, show_spinner=False)
def search_places(text, lat=None, lon=None):
    try:
        return _request_places(text, lat, lon)
    except OSError:
        return _public_place_fallback(text)


def parse_nominatim(rows):
    features = []
    for row in rows:
        address = row.get('address', {})
        features.append(dict(geometry=dict(coordinates=[row.get('lon'), row.get('lat')]),
            properties=dict(countrycode=address.get('country_code'),
                name=row.get('name') or address.get('road') or address.get('suburb') or address.get('city'),
                street=address.get('road'), housenumber=address.get('house_number'),
                city=address.get('city') or address.get('town'), state=address.get('state'),
                district=address.get('county'), postcode=address.get('postcode'))))
    frame = parse_places({'features': features})
    frame['LocationSource'] = 'OpenStreetMap / Nominatim'
    return frame


def _public_place_fallback(text):
    """Rate-limited public search only; registered_area never calls this path."""
    global _LAST_FALLBACK
    if not str(text or '').strip():
        return pd.DataFrame(columns=COLUMNS)
    params = urlencode(dict(q=text, format='jsonv2', addressdetails=1,
                            countrycodes='za', limit=8))
    request = Request('https://nominatim.openstreetmap.org/search?' + params,
        headers={'User-Agent': 'Customer360-GeoMapping-ProviderFinder/1.0'})
    with _FALLBACK_LOCK:
        time.sleep(max(0, 1.1 - (time.monotonic() - _LAST_FALLBACK)))
        _LAST_FALLBACK = time.monotonic()
        with urlopen(request, timeout=15) as response:
            return parse_nominatim(json.load(response))


def _request_places(text, lat=None, lon=None):
    """Uncached request; private member location terms must not enter shared caches."""
    query = (text or '').strip()
    if not query:
        return pd.DataFrame(columns=COLUMNS)
    options = dict(q=query, limit=8, lang='en', bbox='16,-35,33.5,-22')
    if lat is not None and lon is not None:
        options.update(lat=float(lat), lon=float(lon), zoom=14)
    params = urlencode(options)
    request = Request(ENDPOINT + '?' + params, headers={'User-Agent': 'Customer360-ProviderFinder/1.0'})
    with urlopen(request, timeout=12) as response:
        payload = json.load(response)
    return parse_places(payload)


def registered_area(address):
    """Resolve the registered locality, without sending a residential street or member ID."""
    import re
    from .geo import haversine_km
    country = str(address.get('CountryCode') or '').strip().upper()
    if country and country not in {'ZA', 'ZAF', 'RSA', 'SA'}:
        return None
    areas = list(dict.fromkeys(str(address.get(k) or '').strip() for k in ['Town', 'Line3', 'Line2']))
    areas = [v for v in areas if v and not re.search(r'\b(po\s*box|p\s*o\s*box|private bag)\b', v, re.I)]
    postcode = str(address.get('PostCode') or '').strip()
    if not areas and not postcode:
        return None
    matches = _request_places(', '.join(areas + [postcode, 'South Africa']))
    if matches.empty:
        return None
    if postcode:
        matches = matches[(matches.PostCode == '') | (matches.PostCode.str.strip() == postcode)]
    tokens = {t for area in areas for t in re.findall(r'[a-z]{3,}', area.lower())}
    if tokens:
        scores = matches.Label.str.lower().map(lambda label: sum(t in label for t in tokens))
        matches = matches.assign(score=scores).loc[scores > 0].sort_values('score', ascending=False)
    if matches.empty:
        return None
    best = matches.iloc[0]
    tied = matches if 'score' not in matches else matches[matches.score == best.score]
    if len(tied) > 1 and (haversine_km(best.Latitude, best.Longitude, tied.Latitude, tied.Longitude) > 20).any():
        return None
    return dict(lat=float(best.Latitude), lon=float(best.Longitude), geotype='Unknown',
                label='Registered address area: ' + best.Label, province=best.Province,
                source='Registered address area / OpenStreetMap', match_level='Area match; not verified residence')


def search_provider_address(provider):
    """Constrain public practice address matches to its source province and town."""
    from .geo import haversine_km
    province = str(provider.get('ProvinceDescr') or '').strip()
    town = str(provider.get('Town') or provider.get('Suburb') or '').strip()
    anchor = None
    if town:
        areas = search_places(', '.join(v for v in [town, province, 'South Africa'] if v))
        if province:
            areas = areas[areas.Province.str.casefold() == province.casefold()]
        if not areas.empty:
            anchor = areas.iloc[0]
    text = ', '.join(v for v in [str(provider.get('DisplayAddress') or '').strip(), province, 'South Africa'] if v)
    matches = search_places(text, lat=anchor.Latitude if anchor is not None else None,
                            lon=anchor.Longitude if anchor is not None else None)
    matches = matches[~matches.Label.str.strip().str.casefold().isin(['south africa', 'za'])]
    if province:
        matches = matches[matches.Province.str.casefold() == province.casefold()]
    if anchor is not None and not matches.empty:
        distances = haversine_km(anchor.Latitude, anchor.Longitude, matches.Latitude, matches.Longitude)
        matches = matches[distances <= 20]
    return matches.reset_index(drop=True)
