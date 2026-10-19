"""Session isolation and optional lookup checks; fixtures are test-only."""
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from geomap.membership import normalize_number


class MembershipTests(unittest.TestCase):
    def test_number_validation(self):
        self.assertEqual(normalize_number(' 000123 '), '123')
        for value in ['', '0', 'ABC', "1 OR 1=1", '-1', '1.0', '1' * 19]:
            with self.assertRaises(ValueError):
                normalize_number(value)

    def test_optional_lookup_switch_and_failure(self):
        rows = pd.DataFrame([
            dict(MemberNumber='123', BeneficiaryNumber='0', ProdCode='CLAS', SchemeCode='TEST', BeneficiaryRole='Principal'),
            dict(MemberNumber='123', BeneficiaryNumber='1', ProdCode='CLAS', SchemeCode='TEST', BeneficiaryRole='Dependant')])
        class Source:
            def find_members(self, number):
                if number == '888':
                    raise RuntimeError('Service unavailable')
                return rows if number == '123' else rows.iloc[:0]
        script = '''import streamlit as st
from geomap.data import get_source
from geomap.membership import render_membership
with st.sidebar:
    member = render_membership(get_source())
st.write('Available page')
if member:
    st.write(member['ProdCode'])
'''
        with patch('geomap.data.get_source', return_value=Source()):
            app = AppTest.from_string(script).run()
            self.assertFalse(app.exception)
            self.assertTrue(any(m.value == 'Available page' for m in app.markdown))

            app.button[0].click().run()
            self.assertTrue(app.error)
            app.text_input[0].set_value('123')
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state['active_member']['ProdCode'], 'CLAS')
            app.session_state['search_location'] = {'lat': -26, 'lon': 28}
            app.session_state['provider_address_pin'] = {'private': True}
            app.selectbox[0].select(1).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state['active_member']['BeneficiaryNumber'], '1')
            self.assertNotIn('search_location', app.session_state)
            self.assertNotIn('provider_address_pin', app.session_state)
            app.text_input[0].set_value('999')
            app.button[0].click().run()
            self.assertTrue(app.error)
            self.assertNotIn('active_member', app.session_state)
            self.assertTrue(any(m.value == 'Available page' for m in app.markdown))
            app.text_input[0].set_value('888')
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            self.assertNotIn('active_member', app.session_state)

    def test_expired_membership_is_rechecked(self):
        # Expiry is exercised in a real Streamlit session, rather than a mocked session dict.
        script = '''import streamlit as st
from geomap.data import get_source
from geomap.membership import require_member
st.session_state.active_member = dict(MemberNumber='123', BeneficiaryNumber='0', ProdCode='CLAS', SchemeCode='TEST')
st.session_state.membership_checked_at = 0
require_member(get_source())
st.write('Protected page')
'''
        class Source:
            def find_members(self, number):
                return pd.DataFrame(columns=['BeneficiaryNumber', 'ProdCode', 'SchemeCode'])
        with patch('geomap.data.get_source', return_value=Source()):
            app = AppTest.from_string(script).run()
            self.assertFalse(app.exception)
            self.assertNotIn('active_member', app.session_state)


if __name__ == '__main__':
    unittest.main()
