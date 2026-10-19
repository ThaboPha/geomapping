"""One manual, allowlisted export. No personal member records or credentials."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import time
import uuid

ROOT=Path(__file__).resolve().parent
WORK=ROOT/'artifacts/manual_snapshot_build'
PUBLIC=['PracNum','PracNumDisplay','PracName','PracType','PracTypeDescr','ProviderCategory',
 'DisplayAddress','ProvinceDescr','Suburb','Town','PostCode','PracticeEmail','IsNetworkProvider','AddrQualityFlag',
 'Networks','AssBlockActive','EligibilityStatus','PrimaryNetworkInd','Latitude','Longitude','MatchLevel',
 'SpecialistMatchLevel','HospPracNum','HospName','HospMatchLevel','DistanceKm','LocationAlignment']


def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--resume',action='store_true',help='Continue the existing export checkpoints instead of creating a fresh capture.')
    args=parser.parse_args()
    from live_test import _query,app_dir
    from geomap.databricks_source import DatabricksSource
    from geomap.provider_alignment import ProviderAlignmentSource
    source=DatabricksSource(); alignment=ProviderAlignmentSource(source)
    if WORK.exists() and not args.resume:
        if WORK.resolve().parent!=(ROOT/'artifacts').resolve(): raise ValueError('Unexpected build path.')
        WORK.rename(WORK.with_name('manual_snapshot_build_previous_'+uuid.uuid4().hex[:8]))
    WORK.mkdir(exist_ok=True)
    progress=WORK/'progress.json'
    manifest=json.loads(progress.read_text()) if progress.exists() else dict(
        format_version=1,version=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
        started_at=datetime.now(timezone.utc).isoformat(),datasets={})
    def save(name,load,columns=None):
        if name in manifest['datasets']:
            print('Checkpoint retained:',name,flush=True); return
        start=time.monotonic(); frame=load()
        if columns is not None: frame=frame[[c for c in columns if c in frame.columns]]
        denied={'memnum','membernumber','beneficiarynumber','benfcnum','addresskey','line1','line2','line3','membername'}
        if denied & {c.lower() for c in frame.columns}: raise ValueError('Disallowed snapshot columns.')
        path=WORK/(name+'.parquet'); frame.to_parquet(path,index=False)
        manifest['datasets'][name]=dict(file=path.name,rows=len(frame),columns=list(frame.columns),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size,
            captured_at=datetime.now(timezone.utc).isoformat())
        progress.write_text(json.dumps(manifest,indent=2))
        print(f'{name}: {len(frame):,} rows; {time.monotonic()-start:.1f}s; {path.stat().st_size:,} bytes',flush=True)
    save('options',source.options)
    save('disciplines',source.disciplines)
    save('standards',source.standards)
    save('places',lambda:_query('SELECT Place,Town,PostCode,Province,Geotype,Latitude,Longitude FROM hive_metastore.geomap.PlaceCentroid'))
    save('providers',lambda:_query('''SELECT p.PracNum,p.PracNumDisplay,p.PracName,p.PracType,p.PracTypeDescr,
        p.ProviderCategory,p.DisplayAddress,p.ProvinceDescr,p.Suburb,p.Town,p.PostCode,p.PracticeEmail,
        p.IsNetworkProvider,p.AddrQualityFlag,g.Latitude,g.Longitude,g.MatchLevel
        FROM hive_metastore.geomap.ProviderMaster p LEFT JOIN hive_metastore.geomap.PracticeGeocode g ON g.PracNum=p.PracNum'''))
    save('locations',lambda:_query('SELECT PracNum,Latitude,Longitude,MatchLevel FROM hive_metastore.geomap.ProviderLocation'))
    save('links',lambda:_query('''SELECT DISTINCT PracNum,trim(ProdCode) AS ProdCode,NetworkName,
        cast(AssBlockActive AS INT) AS AssBlockActive,cast(PrimaryNetworkInd AS INT) AS PrimaryNetworkInd
        FROM hive_metastore.geomap.ProductNetworkProvider'''))
    save('quality',source.provider_location_quality)
    save('freshness',lambda:__import__('pandas').DataFrame([source.provider_location_freshness()]))
    save('membership_summary',source.membership_summary)
    save('distribution',lambda:source.member_distribution().groupby(['ProdCode','Province'],dropna=False).Members.sum().reset_index())
    for planning in (False,True):
        suffix='_planning' if planning else ''
        save('histogram'+suffix,lambda p=planning:source.access_histogram(planning=p))
        save('readiness'+suffix,lambda p=planning:source.member_assessment_summary(planning=p))
    save('alignment',alignment.alignment,PUBLIC)
    save('hospital_gaps',alignment.hospital_gaps)
    save('hospitals',alignment.network_hospitals,PUBLIC)
    save('recruitment',source.recruitment_targets)
    save('network_expected',source.network_directory,PUBLIC)
    from geomap.place_search import search_places
    save('presentation_places',lambda:search_places('Capital Park Pretoria'))
    import pandas as pd
    assert pd.read_parquet(WORK/'providers.parquet').PracNum.is_unique
    assert pd.read_parquet(WORK/'locations.parquet').PracNum.is_unique
    assert pd.read_parquet(WORK/'disciplines.parquet').PracType.is_unique
    manifest.update(completed_at=datetime.now(timezone.utc).isoformat(),complete=True,
        member_data='Aggregates only; no member identifiers or residential addresses.',
        capture_note='Manual capture interval; underlying live views are evaluated during the build.')
    (WORK/'manifest.json').write_text(json.dumps(manifest,indent=2))
    destination=app_dir/'snapshotdata'
    if destination.resolve().parent!=app_dir.resolve(): raise ValueError('Unexpected snapshot path.')
    staging=app_dir/('snapshotdata_build_'+uuid.uuid4().hex[:8]); staging.mkdir()
    for path in WORK.glob('*.parquet'): shutil.copy2(path,staging/path.name)
    shutil.copy2(WORK/'manifest.json',staging/'manifest.json')
    from geomap.snapshot_source import SnapshotSource
    SnapshotSource(staging)
    backup=app_dir/('snapshotdata_previous_'+uuid.uuid4().hex[:8])
    if destination.exists(): destination.rename(backup)
    try:
        staging.rename(destination)
    except Exception:
        if backup.exists() and not destination.exists(): backup.rename(destination)
        raise
    print('Manual snapshot complete:',manifest['version'],flush=True)


if __name__=='__main__': main()
