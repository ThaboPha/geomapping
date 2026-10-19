"""Selected-option alignment and incomplete-coordinate assessments."""
import unittest
from unittest.mock import patch
import pandas as pd
from geomap.databricks_source import DatabricksSource


class AlignmentTests(unittest.TestCase):
    def test_all_options_uses_confirmed_coordinates_and_shared_option_hospitals(self):
        from geomap.session_geocodes import SessionNetworkSource
        from unittest.mock import Mock
        base = dict(ProvinceDescr='KwaZulu-Natal', PracTypeDescr='GYNAECOLOGY', DisplayAddress='Public street address',
                    Latitude=None, Longitude=None, MatchLevel='Failed')
        directory = pd.DataFrame([
            {**base, 'PracNum': 1, 'PracNumDisplay': '1', 'PracName': 'Specialist', 'ProviderCategory': 'Core Specialist'},
            {**base, 'PracNum': 2, 'PracNumDisplay': '2', 'PracName': 'Shared hospital', 'ProviderCategory': 'Hospital'},
            {**base, 'PracNum': 3, 'PracNumDisplay': '3', 'PracName': 'Other option hospital', 'ProviderCategory': 'Hospital'}])
        source = Mock()
        source.network_directory.return_value = directory
        matches = {str(number): dict(SourceAddress='Public street address', Latitude=latitude, Longitude=28.1)
                   for number, latitude in [(1, -26.1), (2, -26.12), (3, -26.1)]}
        links = pd.DataFrame([dict(PracNum=1, ProdCode='STD'), dict(PracNum=2, ProdCode='STD'), dict(PracNum=3, ProdCode='OTHER')])
        with patch('geomap.databricks_source._cached', return_value=links):
            result = SessionNetworkSource(source, matches).alignment(None)
        self.assertEqual(result.iloc[0].HospPracNum, 2)
        self.assertEqual(result.iloc[0].LocationAlignment, 'Near (<= 5 km)')
        self.assertGreater(result.iloc[0].DistanceKm, 0)

    def test_street_accuracy_required_and_missing_coordinates_not_a_gap(self):
        base = dict(ProvinceDescr='Gauteng', PracTypeDescr='Specialty', Networks='Network',
                    NetworkNames='Network', PracNumDisplay='1', DisplayAddress='Test address')
        directory = pd.DataFrame([
            {**base, 'PracNum': 1, 'PracName': 'Specialist', 'ProviderCategory': 'Core Specialist',
             'Latitude': -26.1, 'Longitude': 28.1, 'MatchLevel': 'Suburb'},
            {**base, 'PracNum': 2, 'PracName': 'Hospital', 'ProviderCategory': 'Hospital',
             'Latitude': -26.1, 'Longitude': 28.1, 'MatchLevel': 'Street'},
            {**base, 'PracNum': 3, 'PracName': 'Unlocated hospital', 'ProviderCategory': 'Hospital',
             'Latitude': None, 'Longitude': None, 'MatchLevel': 'Not geocoded'}])
        src = DatabricksSource.__new__(DatabricksSource)
        disciplines = pd.DataFrame([dict(PracTypeDescr='Specialty', ProviderCategory='Core Specialist')])
        with patch.object(src, 'network_directory', return_value=directory), patch.object(src, 'disciplines', return_value=disciplines):
            aligned = src.alignment('TEST')
            self.assertEqual(aligned.iloc[0].LocationAlignment, 'Near (<= 5 km)')
            self.assertEqual(aligned.iloc[0].HospPracNum, 2)
            gaps = src.hospital_gaps('TEST')
            self.assertEqual(gaps.loc[gaps.Hospital == 'Unlocated hospital', 'Assessment'].iloc[0], 'Not assessed: missing coordinates')
            self.assertEqual(gaps.loc[gaps.Hospital == 'Hospital', 'Nearby'].iloc[0], 1)
            self.assertTrue(pd.isna(gaps.loc[gaps.Hospital == 'Unlocated hospital', 'Nearby'].iloc[0]))

    def test_session_matches_require_same_address_and_do_not_claim_street_precision(self):
        from geomap.session_geocodes import SessionNetworkSource
        from unittest.mock import Mock
        directory = pd.DataFrame([
            dict(PracNumDisplay='1', DisplayAddress='Current public address', Latitude=None, Longitude=None, MatchLevel='Failed'),
            dict(PracNumDisplay='2', DisplayAddress='Changed address', Latitude=None, Longitude=None, MatchLevel='Failed')])
        source = Mock()
        source.network_directory.return_value = directory
        matches = {number: dict(SourceAddress='Current public address', Latitude=-26.1, Longitude=28.1) for number in ['1', '2']}
        result = SessionNetworkSource(source, matches).network_directory('STD')
        self.assertEqual(result.iloc[0].Latitude, -26.1)
        self.assertNotEqual(result.iloc[0].MatchLevel, 'Street')
        self.assertTrue(pd.isna(result.iloc[1].Latitude))
        self.assertTrue(directory.Latitude.isna().all())


if __name__ == '__main__':
    unittest.main()
