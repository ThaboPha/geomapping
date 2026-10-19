import unittest
from member_azure_maps import assess


def feature(kind='Address', confidence='High', codes=None, lon=28.2, country='ZA'):
    return {'geometry': {'coordinates': [lon, -25.7]}, 'properties': {
        'type': kind, 'confidence': confidence, 'matchCodes': codes if codes is not None else ['Good'],
        'address': {'countryRegion': {'ISO': country}}}}


class MatchTests(unittest.TestCase):
    def test_precise_match(self):
        self.assertTrue(assess({'features': [feature()]})['Accepted'])

    def test_approximate_not_promoted(self):
        for kind in ('PopulatedPlace', 'Neighborhood', 'Postcode1', 'RoadBlock'):
            self.assertFalse(assess({'features': [feature(kind=kind)]})['Accepted'])

    def test_ambiguous_not_promoted(self):
        self.assertFalse(assess({'features': [feature(codes=['Good', 'Ambiguous'])]})['Accepted'])
        self.assertFalse(assess({'features': [feature(), feature(lon=29)]})['Accepted'])

    def test_low_confidence_not_promoted(self):
        self.assertFalse(assess({'features': [feature(confidence='Medium')]})['Accepted'])

    def test_nonlocal_not_promoted(self):
        self.assertFalse(assess({'features': [feature(country='BW')]})['Accepted'])

    def test_empty_and_error(self):
        self.assertEqual(assess({})['ResultStatus'], 'NO_MATCH')
        self.assertEqual(assess({'error': {'code': 'BadRequest'}})['ResultStatus'], 'SERVICE_ERROR')

    def test_coordinate_order_and_finite(self):
        self.assertEqual(assess({'features': [feature()]})['Latitude'], -25.7)
        self.assertFalse(assess({'features': [feature(lon=float('nan'))]})['Accepted'])


if __name__ == '__main__':
    unittest.main()
