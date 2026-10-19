"""Validation and session-state checks for patient location capture."""
import os
import unittest

os.environ['GEOMAP_MODE'] = 'databricks'

from geomap.location import ERRORS, validate_location
from streamlit.testing.v1 import AppTest


class LocationValidationTest(unittest.TestCase):
    def test_valid_and_boundaries(self):
        for lat, lon in [(-26.107, 28.057), (-35, 16), (-22, 33.5)]:
            location, error = validate_location(dict(status='success', latitude=lat, longitude=lon, accuracy=20))
            self.assertIsNone(error)
            self.assertEqual(location, dict(lat=lat, lon=lon, accuracy=20))

    def test_invalid_payloads(self):
        for payload in [None, [], {}, {'status':'success'},
                        dict(status='success', latitude=float('nan'), longitude=28, accuracy=20),
                        dict(status='success', latitude=-26, longitude=float('inf'), accuracy=20),
                        dict(status='success', latitude=True, longitude=28, accuracy=20),
                        dict(status='success', latitude=-26, longitude=28, accuracy=-1)]:
            with self.subTest(payload=payload):
                location, error = validate_location(payload)
                self.assertIsNone(location)
                self.assertEqual(error, ERRORS['invalid'])

    def test_outside_region(self):
        for lat, lon in [(51.5, -.1), (-36, 28), (-26, 34)]:
            location, error = validate_location(dict(status='success', latitude=lat, longitude=lon, accuracy=20))
            self.assertIsNone(location)
            self.assertEqual(error, ERRORS['outside_region'])

    def test_error_messages(self):
        for code in ['permission_denied', 'timeout', 'unavailable', 'insecure', 'unsupported']:
            location, error = validate_location(dict(status='error', error=code))
            self.assertIsNone(location)
            self.assertEqual(error, ERRORS[code])

    def test_coordinate_population_and_no_replay(self):
        app = AppTest.from_string('''
import streamlit as st
from types import SimpleNamespace
from unittest.mock import patch
from geomap.location import capture_location
payload = st.session_state.get('test_payload')
with patch('geomap.location._capture', return_value=SimpleNamespace(location=payload)):
    capture_location()
st.segmented_control('Mode', ['Coordinates', 'Suburb or postcode'], key='loc_mode')
st.number_input('Latitude', key='coord_lat')
st.number_input('Longitude', key='coord_lon')
''')
        app.session_state['test_payload'] = dict(status='success', request_id='one', latitude=-26.107, longitude=28.057, accuracy=20)
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.number_input[0].value, -26.107)
        self.assertEqual(app.number_input[1].value, 28.057)
        self.assertEqual(app.session_state['coord_geotype'], 'Unknown')
        app.number_input[0].set_value(-25.7).run()
        self.assertEqual(app.number_input[0].value, -25.7, 'Old component state must not overwrite manual edits')
        app.session_state['test_payload'] = dict(status='error', request_id='two', error='permission_denied')
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.number_input[0].value, -25.7, 'Denied refresh must preserve the prior search')
        self.assertTrue(app.warning)
        app.session_state['test_payload'] = dict(status='success', request_id='three', latitude=-25.747, longitude=28.188, accuracy=100)
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.number_input[0].value, -25.747)
        self.assertFalse(app.warning, 'Successful retry must clear the previous error')


if __name__ == '__main__':
    unittest.main(verbosity=2)
