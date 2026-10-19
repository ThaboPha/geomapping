import unittest
from unittest.mock import patch
import pandas as pd
from geomap.member_geocoding import validate_result
from geomap.databricks_source import DatabricksSource

class MemberPipelineTests(unittest.TestCase):
    def result(self):
        return dict(AddressKey='a'*64,Latitude=-26,Longitude=28,Province='Gauteng',
            District='Example district',Geotype='Metro',MatchLevel='Street',Source='Approved test fixture')
    def test_invalid_results_rejected(self):
        self.assertEqual(validate_result(self.result())['Status'],'MATCHED')
        for field,value in [('AddressKey','123'),('Latitude',float('nan')),('Longitude',0),
                            ('Province','Made up'),('Geotype','Guess'),('MatchLevel','Verified'),('Source',''),('Confidence',2)]:
            with self.subTest(field=field):
                with self.assertRaises((ValueError,TypeError)):
                    validate_result({**self.result(),field:value})
    def test_unknown_classification_preserved(self):
        result=validate_result({**self.result(), 'Geotype':'', 'District':'', 'Province':''})
        self.assertEqual(result['Geotype'],'Unknown')
        self.assertEqual(result['District'],'Unknown')
    def test_weighted_histogram_excludes_unassessed_targets(self):
        schema=pd.DataFrame({'col_name':['MemberCount','AssessmentStatus']})
        src=DatabricksSource.__new__(DatabricksSource)
        with patch('geomap.databricks_source._cached',side_effect=[schema,pd.DataFrame()]) as query:
            src.access_histogram()
            sql=query.call_args_list[-1].args[0]
            self.assertIn('sum(MemberCount)',sql)
            self.assertIn("WHERE AssessmentStatus IN ('ASSESSED', 'MAPPED_DIRECTORY_ESTIMATE')",sql)
    def test_legacy_histogram_contract(self):
        schema=pd.DataFrame({'col_name':['MemberKey','NearestKm']})
        src=DatabricksSource.__new__(DatabricksSource)
        with patch('geomap.databricks_source._cached',side_effect=[schema,pd.DataFrame()]) as query:
            src.access_histogram()
            self.assertIn('count(*) AS Members',query.call_args_list[-1].args[0])
