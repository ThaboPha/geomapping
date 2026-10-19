"""Optional current membership lookup, isolated to each browser session."""
import re
import time

import streamlit as st


def normalize_number(value):
    number = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,18}", number) or int(number) == 0:
        raise ValueError("Enter a valid numeric membership number.")
    return str(int(number))


def clear_member_context():
    for key in list(st.session_state):
        if key not in {"membership_number_input", "membership_beneficiary"}:
            del st.session_state[key]


def require_member(src, optional=False):
    if getattr(src,'is_snapshot',False) is True:
        return None
    member = st.session_state.get("active_member")
    if member and time.time() - st.session_state.get("membership_checked_at", 0) < 300:
        return member
    if member:
        try:
            rows = src.find_members(member["MemberNumber"])
            matches = rows.loc[
                (rows.BeneficiaryNumber.astype(str) == str(member["BeneficiaryNumber"]))
                & (rows.ProdCode == member["ProdCode"])
                & (rows.SchemeCode == member["SchemeCode"])]
            if len(matches) == 1:
                st.session_state.membership_checked_at = time.time()
                return matches.iloc[0].to_dict()
        except Exception:
            clear_member_context()
            st.error("Membership could not be checked. Please try again before continuing.")
            if optional:
                return None
            st.stop()
        clear_member_context()
        st.warning("Your membership has changed. Enter your number again to continue.")
    if optional:
        return None
    st.info("Load a membership in the sidebar to use its registered address, or search by suburb or coordinates.")
    st.stop()


def render_membership(src):
    if getattr(src,'is_snapshot',False) is True:
        for key in ('active_member','membership_records','membership_checked_at','registered_location','registered_address'):
            st.session_state.pop(key,None)
        st.caption('Snapshot mode: search by suburb and benefit option. Personal membership lookup requires live data and is disabled for this trial.')
        return None
    st.subheader("Your membership")
    st.caption("Optional. Search by suburb and select a benefit option without a membership number. Load membership for personalised searches.")
    with st.form("membership_lookup", clear_on_submit=False):
        number = st.text_input("Membership number (optional)", key="membership_number_input", max_chars=18)
        submitted = st.form_submit_button("Load membership")
    if submitted:
        clear_member_context()
        st.session_state.pop("membership_beneficiary", None)
        try:
            number = normalize_number(number)
        except ValueError as exc:
            st.error(str(exc))
        else:
            try:
                with st.spinner("Checking current membership…"):
                    rows = src.find_members(number)
                if rows.empty:
                    st.error("No current active membership was found. Check your membership number.")
                else:
                    st.session_state.membership_records = rows.to_dict("records")
            except Exception:
                st.error("The live membership service is unavailable. Please try again.")
    records = st.session_state.get("membership_records", [])
    if records:
        choice = st.selectbox(
            "Beneficiary", range(len(records)), key="membership_beneficiary",
            format_func=lambda i: f"{records[i]['BeneficiaryRole']} {records[i]['BeneficiaryNumber']} · {records[i]['ProdCode']}")
        selected = records[choice]
        previous = st.session_state.get("active_member")
        if previous != selected:
            clear_member_context()
            st.session_state.membership_records = records
            st.session_state.active_member = selected
            # Recheck a beneficiary switch against the current source, rather
            # than extending validation indefinitely using old dropdown rows.
            st.session_state.membership_checked_at = 0 if previous is not None else time.time()
        st.success(f"Current membership found · option {selected['ProdCode']}")
        st.caption("A membership number identifies a benefit record; it does not verify identity. No names or medical records are displayed.")
    if records and st.button("Continue without membership"):
        clear_member_context()
        st.rerun()
    member = require_member(src, optional=True)
    if member is None:
        return None
    from .registered_location import ensure_registered_location
    ensure_registered_location(src, member)
    return member
