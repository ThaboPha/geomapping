"""Resumable 10,000-address Azure Maps pilot; no addresses or keys in logs/files.

The user authorised Azure Maps processing. Selection and results remain in the
existing private Databricks schema; only address fields go to Azure Maps.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import time

import requests
from member_azure_maps import assess, BoundaryClassifier

ROOT = Path(__file__).resolve().parent
RUN = 'azure-maps-members-20261016-10000'
SAMPLE = 'hive_metastore.geomap_private.AzureMapsMemberPilot20261016'
AUDIT = 'hive_metastore.geomap_private.AzureMapsMemberGeocodeResult'
ACCOUNT = 'geobonlytics-maps'
GROUP = 'rg-lakehouse-AA-Dev-zanorth'
API = '2026-01-01'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-records', type=int, default=10000, choices=range(1,10001), metavar='1..10000')
    args = parser.parse_args()
    from live_test import _query, app_dir

    _query(f'''CREATE TABLE IF NOT EXISTS {SAMPLE} USING DELTA AS
        SELECT AddressKey, AddressType, Line1, Line2, Line3, Town, PostCode, CountryCode, Members
        FROM hive_metastore.geomap_private.MemberGeocodingQueue
        WHERE QueueStatus='READY' AND length(trim(concat_ws(' ',Line1,Line2,Line3)))>=5
          AND NOT upper(concat_ws(' ',Line1,Line2,Line3)) RLIKE 'P[ .]*O[ .]*BOX|PRIVATE BAG|POSTAL BOX'
        ORDER BY sha2(concat(AddressKey,'{RUN}'),256) LIMIT 10000''')
    _query(f'''CREATE TABLE IF NOT EXISTS {AUDIT} (
        RunId STRING,AddressKey STRING,Latitude DOUBLE,Longitude DOUBLE,
        Confidence STRING,FeatureType STRING,MatchCodes ARRAY<STRING>,CalculationMethod STRING,
        ResultStatus STRING,Accepted BOOLEAN,Province STRING,District STRING,Geotype STRING,
        MetroDistanceKm DOUBLE,Source STRING,ProcessedAt TIMESTAMP) USING DELTA''')
    selection = _query(f'''SELECT count(*) AS Addresses,sum(Members) AS Members FROM {SAMPLE}''')
    print('Fixed sample:', selection.to_dict('records'), flush=True)
    pending = _query(f'''SELECT s.* FROM {SAMPLE} s LEFT ANTI JOIN {AUDIT} a
        ON a.RunId=:run AND a.AddressKey=s.AddressKey ORDER BY s.AddressKey LIMIT {args.max_records}''', {'run': RUN})
    print('Pending this invocation:', len(pending), flush=True)
    if not pending.empty:
        result = subprocess.run([sys.executable,'-m','azure.cli','maps','account','keys','list',
            '-g',GROUP,'-n',ACCOUNT,'-o','json'],capture_output=True,text=True)
        if result.returncode:
            raise RuntimeError('Unable to obtain Azure Maps key; no addresses submitted.')
        key = json.loads(result.stdout)['primaryKey']
        http = requests.Session()
        http.headers.update({'subscription-key':key,'Content-Type':'application/json'})
        classifier = BoundaryClassifier(app_dir/'geographic_reference')
        counts = Counter()
        for offset in range(0,len(pending),100):
            batch = pending.iloc[offset:offset+100].to_dict('records')
            queries = []
            for index, row in enumerate(batch):
                queries.append(dict(addressLine=', '.join(str(row.get(k) or '') for k in ('Line1','Line2','Line3') if str(row.get(k) or '').strip()),
                    locality=str(row.get('Town') or ''),postalCode=str(row.get('PostCode') or ''),
                    countryRegion='ZA',top=2,optionalId=str(index)))
            response = None
            for attempt in range(5):
                try:
                    response = http.post(f'https://atlas.microsoft.com/geocode:batch?api-version={API}',
                        json={'batchItems':queries},timeout=(20,90))
                except requests.RequestException:
                    print(f'Batch transport interrupted; retry {attempt+1}/5 (no address data logged).',flush=True)
                    time.sleep(min(30,2**(attempt+1)))
                    continue
                if response.status_code not in (429,500,502,503,504):
                    break
                time.sleep(min(30,2**(attempt+1)))
            if response is None or response.status_code != 200:
                status = response.status_code if response is not None else 'unavailable'
                raise RuntimeError(f'Azure Maps batch failed with HTTP {status}; no address data logged.')
            payload = response.json()
            items = payload.get('batchItems', [])
            if payload.get('nextLink') or len(items) != len(batch):
                raise RuntimeError('Unexpected paginated/incomplete batch; refusing positional result assignment.')
            output = []
            for index, (row,item) in enumerate(zip(batch,items)):
                if str(item.get('optionalId',index)) != str(index):
                    raise RuntimeError('Azure Maps correlation mismatch.')
                assessed = assess(item)
                assessed.update(RunId=RUN,AddressKey=row['AddressKey'],Province='Unknown',District='Unknown',
                    Geotype='Unknown',MetroDistanceKm=None,Source=f'Azure Maps Geocoding {API}')
                if assessed['Accepted']:
                    assessed.update(classifier.classify(assessed['Latitude'],assessed['Longitude']))
                    if assessed['Province']=='Unknown' or assessed['District']=='Unknown':
                        assessed.update(Accepted=False,ResultStatus='REVIEW_BOUNDARY')
                counts[assessed['ResultStatus']] += 1
                output.append(assessed)
            _query(f'''MERGE INTO {AUDIT} target USING (
                SELECT value.* FROM (SELECT explode(from_json(:payload,
                  'ARRAY<STRUCT<RunId:STRING,AddressKey:STRING,Latitude:DOUBLE,Longitude:DOUBLE,
                  Confidence:STRING,FeatureType:STRING,MatchCodes:ARRAY<STRING>,CalculationMethod:STRING,
                  ResultStatus:STRING,Accepted:BOOLEAN,Province:STRING,District:STRING,Geotype:STRING,
                  MetroDistanceKm:DOUBLE,Source:STRING>>')) value)) source
                ON target.RunId=source.RunId AND target.AddressKey=source.AddressKey
                WHEN NOT MATCHED THEN INSERT (RunId,AddressKey,Latitude,Longitude,Confidence,FeatureType,
                  MatchCodes,CalculationMethod,ResultStatus,Accepted,Province,District,Geotype,
                  MetroDistanceKm,Source,ProcessedAt)
                VALUES (source.RunId,source.AddressKey,source.Latitude,source.Longitude,source.Confidence,
                  source.FeatureType,source.MatchCodes,source.CalculationMethod,source.ResultStatus,
                  source.Accepted,source.Province,source.District,source.Geotype,source.MetroDistanceKm,
                  source.Source,current_timestamp())''', {'payload':json.dumps(output)})
            print(f'Checkpoint {offset+len(batch)}/{len(pending)}: {dict(counts)}',flush=True)

    # Conservative promotion: never overwrite coordinates already held by the pipeline.
    _query(f'''MERGE INTO hive_metastore.geomap_private.AddressGeocode target
        USING (SELECT * FROM {AUDIT} WHERE RunId=:run AND Accepted=true) source
        ON target.AddressKey=source.AddressKey
        WHEN NOT MATCHED THEN INSERT (AddressKey,Latitude,Longitude,Province,District,Geotype,
          MatchLevel,Confidence,Source,Status,GeocodedAt)
        VALUES (source.AddressKey,source.Latitude,source.Longitude,source.Province,source.District,
          source.Geotype,'Street',NULL,source.Source,'MATCHED',current_timestamp())''', {'run':RUN})
    summary = _query(f'''SELECT a.ResultStatus,a.Geotype,count(*) AS Addresses,sum(s.Members) AS Members
        FROM {AUDIT} a JOIN {SAMPLE} s ON s.AddressKey=a.AddressKey WHERE a.RunId=:run GROUP BY ALL
        ORDER BY ResultStatus,Geotype''', {'run':RUN})
    print(summary.to_string(index=False),flush=True)
    report = dict(run_id=RUN,api_version=API,account=ACCOUNT,selection=selection.to_dict('records'),
        summary=summary.to_dict('records'),
        note='10,000 distinct residential address records; High/Good Address matches only promoted. Confidence is categorical, not a probability. Official cached boundary geography uses the user-specified distance bands.')
    (ROOT/'artifacts'/'azure_maps_member_pilot_summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
