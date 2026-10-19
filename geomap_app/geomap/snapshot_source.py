"""Read-only, validated snapshot of real Databricks outputs. Never connects to SQL."""
import hashlib
import json
from pathlib import Path
from threading import RLock
import numpy as np
import pandas as pd
from .data import DataSource,SPECIALIST_CATEGORIES
from .geo import bbox,haversine_km

REQUIRED={'options','disciplines','standards','places','providers','locations','links','quality','freshness',
 'membership_summary','distribution','histogram','histogram_planning','readiness','readiness_planning',
 'alignment','hospital_gaps','hospitals','recruitment','network_expected'}


class SnapshotSource(DataSource):
    # Preserve existing network/eligibility UI rules; backend is explicitly labelled separately.
    mode='databricks'
    is_snapshot=True

    def __init__(self,directory):
        self.directory=Path(directory)
        self.manifest=json.loads((self.directory/'manifest.json').read_text())
        if not self.manifest.get('complete') or self.manifest.get('format_version')!=1:
            raise ValueError('Snapshot is incomplete or unsupported.')
        datasets=self.manifest.get('datasets',{})
        if not REQUIRED.issubset(datasets): raise ValueError('Snapshot is missing required datasets.')
        self._frames={}; self._derived={}; self._lock=RLock()
        for name,entry in datasets.items():
            file=entry['file']
            if file!=name+'.parquet' or Path(file).name!=file: raise ValueError('Invalid snapshot path.')
            if hashlib.sha256((self.directory/file).read_bytes()).hexdigest()!=entry['sha256']:
                raise ValueError('Snapshot checksum failed: '+name)

    def _read(self,name):
        with self._lock:
            if name not in self._frames:
                frame=pd.read_parquet(self.directory/self.manifest['datasets'][name]['file'])
                entry=self.manifest['datasets'][name]
                if len(frame)!=entry['rows'] or list(frame.columns)!=entry['columns']:
                    raise ValueError('Snapshot shape failed validation: '+name)
                for column in ('PracNum','Latitude','Longitude','DistanceKm'):
                    if column in frame: frame[column]=pd.to_numeric(frame[column],errors='coerce')
                self._frames[name]=frame
            return self._frames[name].copy()

    def options(self): return self._read('options')
    def disciplines(self): return self._read('disciplines')
    def standards(self): return self._read('standards')
    def membership_summary(self): return self._read('membership_summary')
    def member_distribution(self): return self._read('distribution')
    def access_histogram(self,planning=False): return self._read('histogram_planning' if planning else 'histogram')
    def member_assessment_summary(self,planning=False): return self._read('readiness_planning' if planning else 'readiness')
    def provider_location_quality(self): return self._read('quality')
    def provider_location_freshness(self): return self._read('freshness').iloc[0].to_dict()
    def freshness(self): return self.provider_location_freshness()
    def refresh(self):
        # A presentation reload must never trigger a Databricks refresh.
        with self._lock: self._derived.clear()

    def search_places(self,text):
        value=str(text or '').strip().lower()
        places=self._read('places')
        mask=places.Place.fillna('').str.lower().str.contains(value,regex=False)|places.Town.fillna('').str.lower().str.contains(value,regex=False)|places.PostCode.eq(value)
        result=places[mask].sort_values('Place').head(25).copy()
        result['Label']=(result[['Place','Town','Province','PostCode']].fillna('').astype(str).agg(', '.join,axis=1)
                         if not result.empty else pd.Series(index=result.index,dtype='object'))
        result['LocationSource']='Snapshot locality reference (area coordinates)'
        if 'presentation_places' in self.manifest['datasets']:
            public=self._read('presentation_places')
            found=public[public.Label.fillna('').str.lower().str.contains(value,regex=False)]
            if not found.empty: return found
        return result

    def directory_provinces(self):
        p=self._read('providers')
        return p.loc[p.IsNetworkProvider.eq(1),['ProvinceDescr']].dropna().drop_duplicates().sort_values('ProvinceDescr')

    def location_area(self,lat,lon):
        p=self._read('places').dropna(subset=['Latitude','Longitude'])
        p['DistanceKm']=haversine_km(lat,lon,p.Latitude,p.Longitude)
        return p.sort_values('DistanceKm').head(1)[['Place','Province','DistanceKm']]

    def _eligibility(self,prod):
        links=self._read('links')
        if prod is not None: links=links[links.ProdCode.eq(str(prod).strip())]
        return links.groupby('PracNum').agg(Networks=('NetworkName',lambda s:'; '.join(sorted(set(s.dropna().astype(str))))),
            AssBlockActive=('AssBlockActive','max'),PrimaryNetworkInd=('PrimaryNetworkInd','max')).reset_index()

    def _directory(self,prod,all_providers=False):
        frame=self._read('providers').merge(self._eligibility(prod),on='PracNum',how='left' if all_providers else 'inner',indicator=True)
        frame['EligibilityStatus']=np.select([frame._merge.eq('left_only'),frame.AssBlockActive.isna(),frame.AssBlockActive.ne(0)],
            ['Cover not confirmed for selected option','Unverified assignment status','Assignment blocked; check with scheme'],default='Assignment not blocked')
        return frame.drop(columns='_merge')

    def network_directory(self,prod_code=None):
        return self._directory(prod_code).sort_values(['ProvinceDescr','PracName'],na_position='first').reset_index(drop=True)

    def alignment_directory(self,prod=None):
        frame=self.network_directory(prod)
        located=self._read('locations').drop_duplicates('PracNum').set_index('PracNum')
        missing=frame.Latitude.isna()|frame.Longitude.isna()
        for column in ('Latitude','Longitude','MatchLevel'):
            frame.loc[missing,column]=frame.loc[missing,'PracNum'].map(located[column])
        return frame

    def _planning_coordinates(self):
        key='planning_coordinates'
        with self._lock:
            if key in self._derived: return self._derived[key].copy()
            p=self._read('providers')
            places=self._read('places'); places['Locality']=places.Place.fillna('').str.strip().str.lower()
            grouped=places.groupby(['Locality','PostCode','Province'],dropna=False)[['Latitude','Longitude']].mean().reset_index()
            p['Locality']=p.Suburb.where(p.Suburb.fillna('').str.strip().ne(''),p.Town).fillna('').str.strip().str.lower()
            p=p.merge(grouped,left_on=['Locality','PostCode','ProvinceDescr'],right_on=['Locality','PostCode','Province'],how='left',suffixes=('','_area'))
            missing=p.Latitude.isna(); p.loc[missing,'MatchLevel']=np.where(p.loc[missing,'Latitude_area'].notna(),'Provisional place centroid','Not geocoded')
            for c in ('Latitude','Longitude'): p[c]=p[c].fillna(p[c+'_area'])
            self._derived[key]=p[['PracNum','Latitude','Longitude','MatchLevel']]
            return self._derived[key].copy()

    def providers_near(self,prod_code,lat,lon,category,prac_type,max_km,limit,include_unverified=False,use_place_centroids=False,all_providers=False):
        frame=self._directory(prod_code,all_providers)
        frame=frame[frame.ProviderCategory.eq(category)]
        if prac_type is not None: frame=frame[frame.PracType.eq(int(prac_type))]
        if not all_providers:
            frame=frame[frame.AssBlockActive.eq(0)|(include_unverified & frame.AssBlockActive.isna())]
        if use_place_centroids:
            frame=frame.drop(columns=['Latitude','Longitude','MatchLevel']).merge(self._planning_coordinates(),on='PracNum',how='left')
        south,north,west,east=bbox(lat,lon,max_km)
        frame=frame[frame.Latitude.between(south,north)&frame.Longitude.between(west,east)].copy()
        frame['DistanceKm']=haversine_km(lat,lon,frame.Latitude,frame.Longitude)
        columns=['PracNumDisplay','PracName','PracTypeDescr','DisplayAddress','PracticeEmail','Networks','PrimaryNetworkInd',
            'MatchLevel','EligibilityStatus','Latitude','Longitude','DistanceKm']
        return frame[frame.DistanceKm.le(max_km)].sort_values(['DistanceKm','PracNumDisplay']).head(int(limit))[columns].reset_index(drop=True)

    def unmapped_providers(self,prod_code,category,prac_type,limit,include_unverified=False,province=None,all_providers=False):
        frame=self._directory(prod_code,all_providers)
        frame=frame[frame.ProviderCategory.eq(category)&(frame.Latitude.isna()|frame.Longitude.isna())]
        if prac_type is not None: frame=frame[frame.PracType.eq(int(prac_type))]
        if province: frame=frame[frame.ProvinceDescr.eq(province)]
        if not all_providers: frame=frame[frame.AssBlockActive.eq(0)|(include_unverified & frame.AssBlockActive.isna())]
        frame=frame.copy(); frame['LocationStatus']='Missing provider coordinates'
        columns=['PracNumDisplay','PracName','PracTypeDescr','DisplayAddress','ProvinceDescr','Suburb','Town','PostCode','Networks','LocationStatus','EligibilityStatus']
        return frame.sort_values(['ProvinceDescr','PracName'],na_position='first').head(int(limit))[columns].reset_index(drop=True)

    def alignment(self,prod_code=None):
        if prod_code is None: return self._read('alignment')
        # Filter shared-option relationships first, then recalculate the same distance rules locally.
        from .geo import haversine_km
        directory=self.alignment_directory(prod_code)
        specialists=directory[directory.ProviderCategory.isin(SPECIALIST_CATEGORIES)]
        hospitals=directory[directory.ProviderCategory.eq('Hospital')].dropna(subset=['Latitude','Longitude'])
        rows=[]
        for _,specialist in specialists.iterrows():
            row=specialist.to_dict(); row.update(SpecialistMatchLevel=row['MatchLevel'],HospPracNum=None,HospName=None,HospMatchLevel=None,DistanceKm=None,LocationAlignment='Not geocoded')
            if pd.notna(row['Latitude']) and pd.notna(row['Longitude']):
                row['LocationAlignment']='No mapped network hospital on selected option'
                if not hospitals.empty:
                    distances=haversine_km(row['Latitude'],row['Longitude'],hospitals.Latitude,hospitals.Longitude)
                    hospital=hospitals.loc[distances.idxmin()]; distance=float(distances.min())
                    row.update(HospPracNum=hospital.PracNum,HospName=hospital.PracName,HospMatchLevel=hospital.MatchLevel,DistanceKm=distance,
                        LocationAlignment='On-site / adjacent' if distance<=0.5 and row['MatchLevel']==hospital.MatchLevel=='Street' else 'Near (<= 5 km)' if distance<=5 else 'Distant (> 5 km)')
            rows.append(row)
        return pd.DataFrame(rows,columns=list(specialists.columns)+['SpecialistMatchLevel','HospPracNum','HospName','HospMatchLevel','DistanceKm','LocationAlignment'])

    def network_hospitals(self,prod_code=None):
        if prod_code is None: return self._read('hospitals')
        frame=self.alignment_directory(prod_code); return frame[frame.ProviderCategory.eq('Hospital')].copy()

    def hospital_gaps(self,prod_code=None):
        if prod_code is None: return self._read('hospital_gaps')
        from .provider_alignment import all_hospital_gaps
        links=self._read('links'); links=links[links.ProdCode.eq(prod_code)]
        memberships=links.groupby('PracNum').ProdCode.agg(set).to_dict()
        return all_hospital_gaps(self.alignment_directory(prod_code),self.disciplines(),memberships)

    def recruitment_targets(self,prod_code=None):
        frame=self._read('recruitment')
        if prod_code is not None:
            names=set(self.network_hospitals(prod_code).PracName)
            frame=frame[frame.NetworkHospital.isin(names)]
        return frame

    def address_quality(self):
        frame=self.provider_location_quality()
        return frame.groupby(['ProviderCategory','IsNetworkProvider','AddrQualityFlag','MatchLevel'],dropna=False).size().rename('Practices').reset_index()
