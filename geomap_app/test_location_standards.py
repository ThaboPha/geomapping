import unittest
import pandas as pd
from geomap.location_standards import assess_option

class LocationStandardTests(unittest.TestCase):
    def test_radius_and_missing_coordinates(self):
        rows=pd.DataFrame([dict(PracNumDisplay='1',Latitude=-26.1,Longitude=28.1),dict(PracNumDisplay='2',Latitude=None,Longitude=None)])
        loc=dict(lat=-26,lon=28)
        _, small=assess_option(rows,loc,5)
        self.assertEqual(small['Nearby'],0)
        self.assertEqual(small['Assessment'],'Unresolved: provider locations missing')
        _, large=assess_option(rows,loc,50)
        self.assertEqual(large['Nearby'],1)
        self.assertEqual(large['Unmapped'],1)
        _, mapped=assess_option(rows.iloc[:1],loc,5)
        self.assertEqual(mapped['Assessment'],'Outside tested standard')
        _, empty=assess_option(rows.iloc[:0],loc,5)
        self.assertEqual(empty['Assessment'],'No network providers listed')
