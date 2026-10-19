"""Regression checks for manual option selection without a member record."""
import unittest
from unittest.mock import Mock, patch

import pandas as pd
from streamlit.testing.v1 import AppTest


class OptionalAccessTests(unittest.TestCase):
    def test_location_access_without_membership(self):
        src = Mock()
        src.options.return_value = pd.DataFrame([
            dict(ProdCode='A', OptionName='Option A'),
            dict(ProdCode='B', OptionName='Option B')])
        with patch('geomap.views.coverage.get_source', return_value=src):
            app = AppTest.from_string(
                'from geomap.views.coverage import render_personal\nrender_personal()').run()
            self.assertFalse(app.exception)
            self.assertFalse(app.selectbox(key='access_option').disabled)
            app.selectbox(key='access_option').select('B').run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state['selected_benefit_option'], 'B')
            src.find_members.assert_not_called()

    def test_suburb_default_without_membership(self):
        with patch('geomap.views.lookup.capture_location'), patch('geomap.data.get_source') as source:
            app = AppTest.from_string(
                'from geomap.views.lookup import _location\n'
                'from geomap.data import get_source\n_location(get_source())').run()
            self.assertFalse(app.exception)
            self.assertEqual(app.segmented_control(key='loc_mode').value, 'Suburb or postcode')
            self.assertNotIn('Registered address', app.segmented_control(key='loc_mode').options)
            source.return_value.find_members.assert_not_called()
