"""User-initiated, one-shot browser location capture; coordinates stay in session state."""
from __future__ import annotations

import math
from pathlib import Path

import streamlit as st
from streamlit.components.v2 import component

_ASSETS = Path(__file__).with_name('location_assets')
_HTML = '<button type="button" id="locate">Use my live location</button><p id="status" role="status" aria-live="polite"></p>'
_CSS = '''button {font:inherit; width:100%; padding:.65rem 1rem; cursor:pointer;
      color:white; background:#1F5F8B; border:1px solid #1F5F8B; border-radius:.5rem;}
      button:focus-visible {outline:3px solid #D68C1A; outline-offset:2px;}
      button:disabled {opacity:.65; cursor:wait;}
      p {font:inherit; font-size:.9rem; margin:.4rem 0; color:var(--st-text-color);}
    '''
_JS = (_ASSETS / 'location.js').read_text(encoding='utf-8')


def _capture(**kwargs):
    # Register in the current Streamlit runtime, including independent test runtimes.
    return component('live_location', html=_HTML, css=_CSS, js=_JS)(**kwargs)

ERRORS = {
    'permission_denied': 'Location permission was denied. Allow location in your browser settings and try again, or enter your suburb or postcode.',
    'unavailable': 'Your device could not find your location. Check that device location is switched on, or enter your suburb or postcode.',
    'timeout': 'Finding your location took too long. Try again, or enter your suburb or postcode.',
    'unsupported': 'This browser does not support location sharing. Enter your suburb or postcode instead.',
    'insecure': 'Location sharing needs a secure HTTPS address, or localhost on this computer. Enter your suburb or postcode instead.',
    'outside_region': 'Your location is outside the supported South African search area. Enter a South African suburb or postcode instead.',
    'invalid': 'Your browser returned an invalid location. Try again, or enter your suburb or postcode.',
}


def validate_location(payload):
    if not isinstance(payload, dict) or payload.get('status') != 'success':
        return None, ERRORS.get(payload.get('error') if isinstance(payload, dict) else None, ERRORS['invalid'])
    try:
        values = [payload[k] for k in ('latitude', 'longitude', 'accuracy')]
        if any(isinstance(v, bool) for v in values):
            return None, ERRORS['invalid']
        lat, lon, accuracy = map(float, values)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, ERRORS['invalid']
    if not all(math.isfinite(v) for v in (lat, lon, accuracy)) or accuracy < 0:
        return None, ERRORS['invalid']
    if not (-35 <= lat <= -22 and 16 <= lon <= 33.5):
        return None, ERRORS['outside_region']
    return {'lat': lat, 'lon': lon, 'accuracy': accuracy}, None


def capture_location():
    st.caption('Share your location once to find providers near you. Your browser will ask for permission. '
               'Your coordinates are sent to the app and Databricks for this search; your movement is not tracked.')
    result = _capture(key='live_location_button', on_location_change=lambda: None)
    payload = result.location
    if payload and isinstance(payload, dict) and payload.get('request_id') != st.session_state.get('last_location_request'):
        st.session_state['last_location_request'] = payload.get('request_id')
        location, error = validate_location(payload)
        st.session_state['live_location_error'] = error
        if location:
            st.session_state['location_revision'] = st.session_state.get('location_revision', 0) + 1
            st.session_state['live_location'] = location
            st.session_state['coord_lat'] = location['lat']
            st.session_state['coord_lon'] = location['lon']
            st.session_state['coord_geotype'] = 'Unknown'
            st.session_state['loc_mode'] = 'Coordinates'
    if st.session_state.get('live_location_error'):
        st.warning(st.session_state['live_location_error'])
        if st.session_state.get('live_location'):
            st.caption('Your previous search location is unchanged. It has not been refreshed.')
