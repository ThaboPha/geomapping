"""Alignment-only live area estimates; confirmed network/product links remain intact."""
from .databricks_source import DatabricksSource, _cached
from .data import DataSource
from . import config

class ProviderAlignmentSource:
    def __init__(self,source):
        self.source=source
    def __getattr__(self,name):
        return getattr(self.source,name)
    def network_directory(self,prod=None):
        if getattr(self.source,'is_snapshot',False) is True:
            return self.source.alignment_directory(prod)
        frame=self.source.network_directory(prod).copy()
        locations=_cached(f'SELECT PracNum,Latitude,Longitude,MatchLevel FROM `{config.CATALOG}`.`{config.SCHEMA}`.`ProviderLocation` WHERE IsNetworkProvider=1')
        lookup=locations.drop_duplicates('PracNum').set_index('PracNum')
        missing=frame.Latitude.isna() | frame.Longitude.isna()
        for column in ['Latitude','Longitude','MatchLevel']:
            frame.loc[missing,column]=frame.loc[missing,'PracNum'].map(lookup[column])
        return frame
    def alignment(self,prod=None):
        if getattr(self.source,'is_snapshot',False) is True:
            return self.source.alignment(prod)
        return DatabricksSource.alignment(self,prod)
    def network_hospitals(self,prod=None):
        frame=self.network_directory(prod)
        return frame[frame.ProviderCategory=='Hospital'].copy()
    def hospital_gaps(self,prod=None):
        if getattr(self.source,'is_snapshot',False) is True:
            return self.source.hospital_gaps(prod)
        directory=self.network_directory(prod)
        links=_cached(f"SELECT DISTINCT PracNum,trim(ProdCode) AS ProdCode FROM `{config.CATALOG}`.`{config.SCHEMA}`.`ProductNetworkProvider`")
        memberships=links.groupby('PracNum').ProdCode.agg(set).to_dict()
        return all_hospital_gaps(directory,self.disciplines(),memberships)


def all_hospital_gaps(directory,disciplines,memberships):
    import pandas as pd
    from .geo import haversine_km
    from .coordinate_quality import reliable_address
    hospitals=directory[directory.ProviderCategory=='Hospital']
    specialists=directory[directory.ProviderCategory.isin(['Core Specialist','Other Specialist','Hospital-based Specialist'])]
    core=disciplines.loc[disciplines.ProviderCategory.isin(['Core Specialist','Hospital-based Specialist']),'PracTypeDescr'].drop_duplicates()
    rows=[]
    for hospital in hospitals.itertuples():
        options=memberships.get(hospital.PracNum,set())
        candidates=specialists[specialists.PracNum.map(lambda key:bool(options & memberships.get(key,set())))]
        for discipline in core:
            selected=candidates[candidates.PracTypeDescr==discipline]
            mapped=selected.dropna(subset=['Latitude','Longitude'])
            mapped=mapped[mapped.MatchLevel.map(reliable_address)]
            nearby=0
            hospital_located=(pd.notna(hospital.Latitude) and pd.notna(hospital.Longitude)
                              and reliable_address(hospital.MatchLevel))
            if hospital_located and not mapped.empty:
                nearby=int((haversine_km(hospital.Latitude,hospital.Longitude,mapped.Latitude,mapped.Longitude)<=5).sum())
            status='Mapped specialist nearby' if nearby else 'Not assessed: missing coordinates' if not hospital_located or len(mapped)<len(selected) else 'No mapped specialist nearby'
            rows.append(dict(Hospital=hospital.PracName,Province=hospital.ProvinceDescr,Discipline=discipline,
                Nearby=nearby if status!='Not assessed: missing coordinates' else None,Assessment=status))
    return pd.DataFrame(rows,columns=['Hospital','Province','Discipline','Nearby','Assessment'])
