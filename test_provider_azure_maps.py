import unittest
from unittest.mock import Mock
from provider_azure_maps import clean_address,assess_provider,coordinate_level


class ProviderGeocodeTests(unittest.TestCase):
    def test_room_removal_preserves_building_and_street(self):
        row=dict(AddrType='S',DisplayAddress='Suite 12, Hospital, 10 Main Road',Line1='Suite 12',
                 Line2='Hospital',Line3='10 Main Road',Town='Town',Suburb='',PostCode='0001')
        _,request=clean_address(row)
        self.assertNotIn('Suite',request['addressLine'])
        self.assertIn('10 Main Road',request['addressLine'])
        self.assertIsNone(clean_address({**row,'AddrType':'P'}))
        self.assertIsNone(clean_address({**row,'DisplayAddress':'PO BOX 12'}))

    def test_match_requires_known_precision_and_matching_postcode(self):
        item={'features':[{'geometry':{'coordinates':[28,-26]},'properties':{'type':'Address',
            'confidence':'High','matchCodes':['Good'],'address':{'countryRegion':{'ISO':'ZA'},'postalCode':'0001'},
            'geocodePoints':[{'geometry':{'coordinates':[28,-26]},'calculationMethod':'Rooftop','usageTypes':['Display']}]}}]}
        classifier=Mock(); classifier.classify.return_value=dict(Province='Gauteng',District='City',Geotype='Metro',MetroDistanceKm=0)
        self.assertTrue(assess_provider(item,{'postalCode':'1'},classifier)['Accepted'])
        self.assertFalse(assess_provider(item,{'postalCode':'9999'},classifier)['Accepted'])
        self.assertNotEqual(coordinate_level('Rooftop'),'Street')
        self.assertIn('premises unverified',coordinate_level('Rooftop'))


if __name__=='__main__': unittest.main()
