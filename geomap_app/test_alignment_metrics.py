import unittest
import pandas as pd
from geomap.alignment_metrics import distance_summary
from geomap.address_estimates import select_address_estimate


class DistanceMetricsTests(unittest.TestCase):
    def test_five_km_boundary_and_missing_distances(self):
        result = distance_summary(pd.DataFrame({'DistanceKm': [0, 4.99, 5, 5.01, None, -1]}))
        self.assertEqual((result['within'], result['above'], result['unknown']), (3, 1, 2))
        self.assertEqual((result['within_pct'], result['above_pct']), (75, 25))
        self.assertIsNone(distance_summary(pd.DataFrame({'DistanceKm': [None]}))['above_pct'])

    def test_ambiguous_or_locality_only_matches_are_not_coordinates(self):
        provider = dict(DisplayAddress='36 Aurora Drive, Umhlanga', Town='Umhlanga', ProvinceDescr='KwaZulu-Natal')
        town = pd.DataFrame([dict(Label='Umhlanga, KwaZulu-Natal', Latitude=-29.7, Longitude=31.1)])
        self.assertIsNone(select_address_estimate(provider, town))
        ambiguous = pd.DataFrame([dict(Label='Aurora Drive', Latitude=lat, Longitude=31.1) for lat in [-29.7, -29.8]])
        self.assertIsNone(select_address_estimate(provider, ambiguous))
        match = select_address_estimate(provider, ambiguous.head(1))
        self.assertEqual(match['Latitude'], -29.7)
        self.assertNotEqual(match['MatchLevel'], 'Street')
