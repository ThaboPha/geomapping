import unittest
import pandas as pd
from geomap.provider_alignment import all_hospital_gaps

class ProviderGapTests(unittest.TestCase):
    def test_every_nearby_shared_option_hospital_is_counted(self):
        base=dict(ProvinceDescr='Gauteng',Latitude=-26,Longitude=28,PracTypeDescr='Core',MatchLevel='Street')
        rows=pd.DataFrame([
            dict(base,PracNum=1,PracName='Specialist',ProviderCategory='Core Specialist'),
            dict(base,PracNum=2,PracName='Hospital A',ProviderCategory='Hospital'),
            dict(base,PracNum=3,PracName='Hospital B',ProviderCategory='Hospital'),
            dict(base,PracNum=4,PracName='Unshared hospital',ProviderCategory='Hospital')])
        disc=pd.DataFrame([dict(PracTypeDescr='Core',ProviderCategory='Core Specialist')])
        result=all_hospital_gaps(rows,disc,{1:{'A'},2:{'A'},3:{'A'},4:{'B'}})
        self.assertEqual(result.loc[result.Hospital=='Hospital A','Nearby'].iloc[0],1)
        self.assertEqual(result.loc[result.Hospital=='Hospital B','Nearby'].iloc[0],1)
        self.assertEqual(result.loc[result.Hospital=='Unshared hospital','Nearby'].iloc[0],0)
        rows.loc[rows.PracNum==1,'Latitude']=None
        result=all_hospital_gaps(rows,disc,{1:{'A'},2:{'A'},3:{'A'},4:{'B'}})
        self.assertEqual(result.iloc[0].Assessment,'Not assessed: missing coordinates')

    def test_centroids_cannot_confirm_hospital_gaps_or_coverage(self):
        base=dict(ProvinceDescr='Gauteng',Latitude=-26,Longitude=28,PracTypeDescr='Core')
        rows=pd.DataFrame([
            dict(base,PracNum=1,PracName='Specialist',ProviderCategory='Core Specialist',MatchLevel='Suburb'),
            dict(base,PracNum=2,PracName='Hospital',ProviderCategory='Hospital',MatchLevel='Street')])
        disc=pd.DataFrame([dict(PracTypeDescr='Core',ProviderCategory='Core Specialist')])
        result=all_hospital_gaps(rows,disc,{1:{'A'},2:{'A'}})
        self.assertEqual(result.iloc[0].Assessment,'Not assessed: missing coordinates')
        rows.loc[rows.PracNum==1,'MatchLevel']='Azure Maps address (Rooftop; premises unverified)'
        result=all_hospital_gaps(rows,disc,{1:{'A'},2:{'A'}})
        self.assertEqual(result.iloc[0].Assessment,'Mapped specialist nearby')
