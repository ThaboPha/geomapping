import unittest
from unittest.mock import patch
import pandas as pd
from geomap.databricks_source import DatabricksSource


class RecruitmentQualityTests(unittest.TestCase):
    def test_unverified_address_cannot_trigger_recruitment_spatial_join(self):
        src=DatabricksSource.__new__(DatabricksSource)
        hospitals=pd.DataFrame([dict(MatchLevel='Azure Maps address (Rooftop; premises unverified)')])
        with patch.object(src,'network_hospitals',return_value=hospitals),patch('geomap.databricks_source._cached') as sql:
            result=src.recruitment_targets()
        self.assertTrue(result.empty)
        sql.assert_not_called()
