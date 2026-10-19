"""Selected beneficiary address defaults, held only in their browser session."""
import streamlit as st
from .place_search import registered_area


def ensure_registered_location(src, member):
    identity = (str(member['MemberNumber']), str(member['BeneficiaryNumber']))
    if st.session_state.get('registered_address_identity') == identity:
        return st.session_state.get('registered_location')
    for key in ['registered_location', 'registered_address', 'registered_address_error']:
        st.session_state.pop(key, None)
    st.session_state.registered_address_identity = identity
    try:
        address = src.registered_address(*identity)
        st.session_state.registered_address = address
        if not address:
            st.session_state.registered_address_error = 'No current registered address is available. Use your live location or enter your address.'
            return None
        with st.spinner('Locating your registered address area…'):
            loc = registered_area(address)
        st.session_state.registered_location = loc
        if loc:
            st.session_state.search_location = loc
        else:
            st.session_state.registered_address_error = 'Your registered address could not be matched reliably. Enter your address or use your live location.'
        return loc
    except Exception:
        st.session_state.registered_address_error = 'Registered address lookup is unavailable. Retry it or use your live location / address search.'
        return None


def show_registered_location(src, member):
    loc = ensure_registered_location(src, member)
    address = st.session_state.get('registered_address')
    if address:
        st.caption(f"Address source: {address['AddressSource']} · type {address['AddressType']}")
        area = ', '.join(dict.fromkeys(str(address.get(k) or '').strip() for k in ['Line2', 'Line3', 'Town', 'PostCode'] if str(address.get(k) or '').strip()))
        st.write('Registered area: ' + area)
        st.caption('Your registered locality and postcode are matched using OpenStreetMap / Photon. No membership number or street address is sent. This is an area estimate, not a verified home position.')
        if address['AddressType'].upper() == 'P':
            st.warning('The registered address is marked postal. Its locality is used as an approximate starting point; confirm your actual location before travelling.')
    if not loc:
        st.warning(st.session_state.get('registered_address_error', 'Choose a search location.'))
    if st.button('Retry registered address', key='retry_registered_address'):
        st.session_state.pop('registered_address_identity', None)
        st.session_state.pop('registered_address_error', None)
        st.rerun()
    return loc
