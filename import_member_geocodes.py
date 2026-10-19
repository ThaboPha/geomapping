"""Import approved geocoder CSV results; dry-run by default. Never log addresses."""
import argparse
import csv
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).parent/'geomap_app'))
from geomap.member_geocoding import validate_result

parser=argparse.ArgumentParser()
parser.add_argument('csv_file',type=Path)
parser.add_argument('--apply',action='store_true')
args=parser.parse_args()
with args.csv_file.open(encoding='utf-8-sig',newline='') as stream:
    records=[validate_result(row) for row in csv.DictReader(stream)]
if len({r['AddressKey'] for r in records})!=len(records):
    raise ValueError('Duplicate AddressKey in import.')
print(f'Validated {len(records)} geocoding results.',flush=True)
if args.apply:
    from live_test import app_dir
    from geomap.databricks_source import _query
    for row in records:
        exists=_query('SELECT count(*) AS Records FROM hive_metastore.geomap_private.MemberAddressPopulation WHERE AddressKey=:key',{'key':row['AddressKey']})
        if not int(exists.iloc[0].Records):
            raise ValueError('An imported key does not exist in the member address population.')
    # Validate all keys before modifying any records.
    for row in records:
        _query('''MERGE INTO hive_metastore.geomap_private.AddressGeocode target
            USING (SELECT :AddressKey AS AddressKey,:Latitude AS Latitude,:Longitude AS Longitude,
                :Province AS Province,:District AS District,:Geotype AS Geotype,:MatchLevel AS MatchLevel,
                CAST(:Confidence AS DOUBLE) AS Confidence,:Source AS Source,:Status AS Status) source
            ON target.AddressKey=source.AddressKey
            WHEN MATCHED THEN UPDATE SET target.Latitude=source.Latitude,target.Longitude=source.Longitude,
                target.Province=source.Province,target.District=source.District,target.Geotype=source.Geotype,
                target.MatchLevel=source.MatchLevel,target.Confidence=source.Confidence,
                target.Source=source.Source,target.Status=source.Status,target.GeocodedAt=current_timestamp()
            WHEN NOT MATCHED THEN INSERT (AddressKey,Latitude,Longitude,Province,District,Geotype,
                MatchLevel,Confidence,Source,Status,GeocodedAt)
            VALUES (source.AddressKey,source.Latitude,source.Longitude,source.Province,source.District,
                source.Geotype,source.MatchLevel,source.Confidence,source.Source,source.Status,current_timestamp())''',row)
    print('Imported results. MemberLocation and MemberAccess views now use them.',flush=True)
else:
    print('Dry run only. Use --apply to load approved results.')
