"""Registered-area confidence and private request boundaries."""
import unittest
from unittest.mock import patch
import pandas as pd
from geomap.place_search import registered_area, COLUMNS


class RegisteredAreaTests(unittest.TestCase):
    def test_private_street_and_member_number_not_sent(self):
        frame = pd.DataFrame([dict(Place='Area', Town='Town', PostCode='1234', Province='Gauteng',
            Geotype='Unknown', Latitude=-26.1, Longitude=28.1, Label='Area, Town, 1234', LocationSource='OpenStreetMap')], columns=COLUMNS)
        with patch('geomap.place_search._request_places', return_value=frame) as request:
            loc = registered_area(dict(Line1='99 Private Street', Line2='Area', Line3='Town', PostCode='1234', CountryCode='ZAF'))
            self.assertIsNotNone(loc)
            self.assertEqual(loc['geotype'], 'Unknown')
            self.assertNotIn('Private Street', request.call_args.args[0])
            self.assertEqual(loc['match_level'], 'Area match; not verified residence')

    def test_rejects_wrong_postcode_country_or_ambiguous_areas(self):
        rows = pd.DataFrame([dict(Place='Town', Town='Town', PostCode='1234', Province='Gauteng',
            Geotype='Unknown', Latitude=-26.1, Longitude=28.1, Label='Town, 1234', LocationSource='OpenStreetMap'),
            dict(Place='Town', Town='Town', PostCode='1234', Province='Western Cape', Geotype='Unknown',
                 Latitude=-33.1, Longitude=18.1, Label='Town, 1234', LocationSource='OpenStreetMap')], columns=COLUMNS)
        with patch('geomap.place_search._request_places', return_value=rows):
            self.assertIsNone(registered_area(dict(Town='Town', PostCode='9999')))
            self.assertIsNone(registered_area(dict(Town='Town', CountryCode='US')))
            self.assertIsNone(registered_area(dict(Town='Town', PostCode='1234')))


if __name__ == '__main__':
    unittest.main()
