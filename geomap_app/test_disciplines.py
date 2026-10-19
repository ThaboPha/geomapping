import unittest
import pandas as pd
from geomap.disciplines import provider_categories, discipline_label


class DisciplineSelectionTests(unittest.TestCase):
    def test_live_categories_do_not_drop_hospital_based_or_unclassified_codes(self):
        frame = pd.DataFrame([
            dict(PracType=10,PracTypeDescr='ANAESTHETICS',ProviderCategory='Hospital-based Specialist'),
            dict(PracType=72,PracTypeDescr='PHYSIOTHERAPY',ProviderCategory='Unclassified')])
        self.assertIn('Hospital-based Specialist',provider_categories(frame))
        self.assertIn('Unclassified',provider_categories(frame))
        self.assertEqual(discipline_label(72,frame),'72 — PHYSIOTHERAPY')
        self.assertEqual(discipline_label(None,frame),'Any discipline')

    def test_same_name_codes_remain_distinguishable(self):
        frame=pd.DataFrame([dict(PracType=14,PracTypeDescr='GENERAL PRACTICE'),
                            dict(PracType=15,PracTypeDescr='GENERAL PRACTICE')])
        self.assertNotEqual(discipline_label(14,frame),discipline_label(15,frame))
