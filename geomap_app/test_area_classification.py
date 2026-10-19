import unittest
from geomap.area_classification import contains,classify_point

def feature(properties,coordinates):
    return dict(properties=properties,geometry=dict(type='Polygon',coordinates=coordinates))

class AreaClassificationTests(unittest.TestCase):
    def setUp(self):
        self.outer=[[0,0],[10,0],[10,10],[0,10],[0,0]]
        self.hole=[[3,3],[7,3],[7,7],[3,7],[3,3]]
    def test_holes_and_disjoint_esri_rings(self):
        self.assertFalse(contains(dict(type='Polygon',coordinates=[self.outer,self.hole]),5,5))
        self.assertTrue(contains(dict(type='Polygon',coordinates=[self.outer,self.hole]),1,1))
        second=[[20,0],[30,0],[30,10],[20,10],[20,0]]
        self.assertTrue(contains(dict(type='EsriPolygon',rings=[self.outer,second]),25,5))
    def test_no_rural_fallback_for_non_metro(self):
        province=feature({'ProvinceName':'Gauteng'},[self.outer])
        muni=feature({'Category':'B','DistrictName':'Example district'},[self.outer])
        self.assertEqual(classify_point(1,1,[muni],[province])['Geotype'],'Unknown')
        settlement=feature({'Geotype':'Rural'},[self.outer])
        self.assertEqual(classify_point(1,1,[muni],[province],[settlement])['Geotype'],'Rural')
    def test_metro_precedence_and_overlap_rejected(self):
        province=feature({'ProvinceName':'Gauteng'},[self.outer])
        muni=feature({'Category':'A','DistrictName':'Metro district'},[self.outer])
        self.assertEqual(classify_point(1,1,[muni],[province])['Geotype'],'Metro')
        self.assertEqual(classify_point(1,1,[muni,muni],[province])['Geotype'],'Unknown')

    def test_user_distance_bands(self):
        from geomap.area_classification import distance_area
        for value,expected in [(0,'Metro'),(9.99,'Metro'),(10,'Urban'),(39.99,'Urban'),(40,'Rural'),(100,'Rural')]:
            self.assertEqual(distance_area(value),expected)
