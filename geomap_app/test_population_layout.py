import unittest
from unittest.mock import Mock, patch
import pandas as pd
from streamlit.testing.v1 import AppTest

class PopulationLayoutTests(unittest.TestCase):
    def source(self):
        src=Mock()
        src.member_distribution.return_value=pd.DataFrame()
        src.options.return_value=pd.DataFrame([dict(ProdCode='A',OptionName='Plan A')])
        src.standards.return_value=pd.DataFrame([dict(ProviderCategory='GP',Geotype=g,RadiusKm=10,TargetCoveragePct=90) for g in ['Metro','Urban','Rural']])
        src.disciplines.return_value=pd.DataFrame(columns=['ProviderCategory','PracTypeDescr'])
        src.directory_provinces.return_value=pd.DataFrame({'ProvinceDescr':['Gauteng']})
        return src
    def test_member_counts_and_gap_percentages(self):
        src=self.source()
        src.access_histogram.return_value=pd.DataFrame([dict(ProdCode='A',Geotype='Metro',Province='Gauteng',District='Sandton',ProviderCategory='GP',Discipline='GP',KmBin=km,Members=n) for km,n in [(5,80),(20,20)]])
        with patch('geomap.views.member_population.get_source',return_value=src):
            app=AppTest.from_string('from geomap.views.member_population import render\nrender()').run()
            self.assertFalse(app.exception)
            option=app.dataframe[0].value
            gaps=app.dataframe[1].value
            self.assertEqual(option.iloc[0]['Members'],100)
            self.assertEqual(option.iloc[0]['Within standard %'],80)
            self.assertEqual(gaps.iloc[0]['Members outside'],20)
            self.assertEqual(gaps.iloc[0]['% outside'],20)
            app.slider(key='r_GP_Metro').set_value(30).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.dataframe[0].value.iloc[0]['Within standard %'],100)
    def test_missing_population_does_not_invent_members(self):
        src=self.source()
        src.access_histogram.side_effect=RuntimeError('TABLE_OR_VIEW_NOT_FOUND')
        with patch('geomap.views.member_population.get_source',return_value=src):
            app=AppTest.from_string('from geomap.views.member_population import render\nrender()').run()
            self.assertFalse(app.exception)
            self.assertTrue(app.dataframe[0].value['Members'].isna().all())
            self.assertEqual(list(app.dataframe[1].value.columns),['Province','District','Area','Members outside','Members','% outside'])

    def test_live_distribution_plan_shares_and_unknown_geography(self):
        src=self.source()
        src.access_histogram.side_effect=RuntimeError('TABLE_OR_VIEW_NOT_FOUND')
        src.member_distribution.return_value=pd.DataFrame([
            dict(ProdCode='A',Province='Gauteng',Locality='Sandton',Members=80),
            dict(ProdCode='B',Province='Unknown',Locality='Unknown',Members=20)])
        with patch('geomap.views.member_population.get_source',return_value=src):
            app=AppTest.from_string('from geomap.views.member_population import render\nrender()').run()
            self.assertFalse(app.exception)
            plans=app.dataframe[0].value
            self.assertEqual(plans.Members.sum(),100)
            self.assertEqual(plans.iloc[0]['% of selected members'],80)
            self.assertTrue(plans['Within standard %'].isna().all())
            self.assertTrue(app.dataframe[1].value['Members outside'].isna().all())

    def test_original_layout_has_no_geography_section(self):
        src=self.source()
        src.access_histogram.return_value=pd.DataFrame([dict(ProdCode='A',Geotype='Metro',Province='Gauteng',District='Tshwane',ProviderCategory='GP',Discipline='GP',KmBin=5,Members=100)])
        src.member_assessment_summary.return_value=pd.DataFrame([dict(ProdCode='A',Geotype='Metro',Province='Gauteng',District='Tshwane',ProviderCategory='GP',Discipline='GP',AssessmentStatus='MAPPED_DIRECTORY_ESTIMATE',Members=100)])
        with patch('geomap.views.member_population.get_source',return_value=src):
            app=AppTest.from_string('from geomap.views.member_population import render\nrender()').run()
            self.assertFalse(app.exception)
            self.assertFalse(any('Member geography coverage' in h.value for h in app.subheader))
            self.assertEqual(len(app.metric),3)
            self.assertEqual(app.metric[0].value,'100.0%')
