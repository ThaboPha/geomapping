"""Reject invalid and foreign place results instead of silently using a bad centroid."""
import unittest
from unittest.mock import patch
from geomap.place_search import parse_places, search_provider_address

class PlaceSearchTest(unittest.TestCase):
    def test_real_coordinates_labels_and_rejections(self):
        def feature(coords, code='ZA'):
            return dict(geometry=dict(coordinates=coords), properties=dict(
                countrycode=code, name='Braamfontein', city='Johannesburg', state='Gauteng'))
        result = parse_places(dict(features=[feature([28.036135, -26.192301]),
            feature([28.036135, -26.192301]), feature([float('nan'), -26]),
            feature([28, 51]), feature([28, -26], 'GB'), feature([])]))
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0].Latitude, -26.192301)
        self.assertEqual(result.iloc[0].Longitude, 28.036135)
        self.assertIn('Johannesburg', result.iloc[0].Label)

    def test_provider_match_rejects_wrong_province_and_town_area(self):
        def places(values):
            return parse_places(dict(features=[dict(geometry=dict(coordinates=[lon, lat]),
                properties=dict(countrycode='ZA', name='Voortrekker Road', state=province))
                for lat, lon, province in values]))
        anchor = places([(-25.78, 28.15, 'Gauteng')])
        candidates = places([(-25.780523, 28.155215, 'Gauteng'),
                             (-26.192301, 28.036135, 'Gauteng'), (-25.78, 28.15, 'Mpumalanga')])
        with patch('geomap.place_search.search_places', side_effect=[anchor, candidates]):
            matches = search_provider_address(dict(DisplayAddress='Voortrekker Road, Thaba Tshwane',
                                                     Town='Thaba Tshwane', ProvinceDescr='Gauteng'))
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches.iloc[0].Latitude, -25.780523)

if __name__ == '__main__':
    unittest.main()


class PublicFallbackTests(unittest.TestCase):
    def test_nominatim_parser_preserves_capital_park_source(self):
        from geomap.place_search import parse_nominatim
        frame=parse_nominatim([dict(name='Capital Park',lat='-25.7241667',lon='28.1877778',
            address=dict(country_code='za',city='Pretoria',state='Gauteng'))])
        self.assertEqual(frame.iloc[0].Place,'Capital Park')
        self.assertEqual(frame.iloc[0].LocationSource,'OpenStreetMap / Nominatim')
        self.assertTrue(parse_nominatim([dict(name='Other',lat='0',lon='0',address=dict(country_code='za'))]).empty)

    def test_timeout_uses_public_fallback(self):
        from geomap.place_search import search_places
        from unittest.mock import patch
        search_places.clear()
        with patch('geomap.place_search._request_places',side_effect=TimeoutError), patch('geomap.place_search._public_place_fallback',return_value='public result') as fallback:
            self.assertEqual(search_places('Capital Park'),'public result')
            fallback.assert_called_once_with('Capital Park')
        search_places.clear()
