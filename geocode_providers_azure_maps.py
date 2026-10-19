"""Geocode current contracted hospitals/specialists; retain a complete result audit."""
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import time
import requests
from member_azure_maps import BoundaryClassifier
from provider_azure_maps import clean_address,assess_provider,coordinate_level

RUN='azure-maps-network-providers-20261019'
SNAPSHOT='hive_metastore.geomap_private.AzureMapsProviderSample20261019'
AUDIT='hive_metastore.geomap_private.AzureMapsProviderResult'


def main():
    from live_test import _query,app_dir
    _query(f'''CREATE TABLE IF NOT EXISTS {SNAPSHOT} USING DELTA AS SELECT *
        FROM hive_metastore.geomap.ProviderLocation WHERE IsNetworkProvider=1 AND
        ProviderCategory IN ('Hospital','Core Specialist','Other Specialist','Hospital-based Specialist')''')
    _query('''CREATE TABLE IF NOT EXISTS hive_metastore.geomap_private.ProviderAddressGeocodeBeforeAzure20261019
        USING DELTA AS SELECT * FROM hive_metastore.geomap.ProviderAddressGeocode''')
    _query(f'''CREATE TABLE IF NOT EXISTS {AUDIT} (RunId STRING,QueryKey STRING,Latitude DOUBLE,Longitude DOUBLE,
        Confidence STRING,FeatureType STRING,MatchCodes ARRAY<STRING>,CalculationMethod STRING,
        ResultStatus STRING,Accepted BOOLEAN,MapAddress STRING,Province STRING,District STRING,Geotype STRING,
        ReturnedPostCode STRING,ProcessedAt TIMESTAMP) USING DELTA''')
    frame=_query(f'SELECT * FROM {SNAPSHOT}')
    rows=frame.where(frame.notna(),None).to_dict('records')
    queries={}; members={}; invalid=[]
    for row in rows:
        cleaned=clean_address(row)
        if not cleaned:
            invalid.append(str(row['PracNumDisplay'])); continue
        key,request=cleaned; queries[key]=request; members.setdefault(key,[]).append(row)
    done=set(_query(f'SELECT QueryKey FROM {AUDIT} WHERE RunId=:run',{'run':RUN}).QueryKey)
    pending=[key for key in queries if key not in done]
    print(f'Providers: {len(rows)}; eligible: {sum(map(len,members.values()))}; unique requests: {len(queries)}; no usable address: {len(invalid)}; pending: {len(pending)}',flush=True)
    if pending:
        key_result=subprocess.run([sys.executable,'-m','azure.cli','maps','account','keys','list','-g','rg-lakehouse-AA-Dev-zanorth','-n','geobonlytics-maps','-o','json'],capture_output=True,text=True,check=True)
        http=requests.Session(); http.headers['subscription-key']=json.loads(key_result.stdout)['primaryKey']
        classifier=BoundaryClassifier(app_dir/'geographic_reference')
        for offset in range(0,len(pending),50):
            keys=pending[offset:offset+50]
            body={'batchItems':[{**queries[k],'optionalId':str(i)} for i,k in enumerate(keys)]}
            response=None
            for attempt in range(5):
                try:
                    response=http.post('https://atlas.microsoft.com/geocode:batch?api-version=2026-01-01',json=body,timeout=(20,75))
                    if response.status_code not in (429,500,502,503,504): break
                except requests.RequestException:
                    pass
                time.sleep(min(20,2**attempt))
            if response is None or response.status_code!=200:
                raise RuntimeError('Azure Maps batch did not succeed; completed checkpoints are retained.')
            payload=response.json(); items=payload.get('batchItems',[])
            if payload.get('nextLink') or len(items)!=len(keys): raise RuntimeError('Incomplete batch response.')
            output=[]
            for i,(key,item) in enumerate(zip(keys,items)):
                if str(item.get('optionalId',i))!=str(i): raise RuntimeError('Correlation mismatch.')
                result=assess_provider(item,queries[key],classifier)
                expected={r['ProvinceDescr'] for r in members[key] if r.get('ProvinceDescr')}
                if result['Accepted'] and (len(expected)!=1 or result['Province'] not in expected):
                    result.update(Accepted=False,ResultStatus='REVIEW_PROVINCE_CONFLICT')
                result.update(RunId=RUN,QueryKey=key)
                result.pop('MetroDistanceKm',None)
                output.append(result)
            _query(f'''MERGE INTO {AUDIT} t USING (SELECT value.* FROM (SELECT explode(from_json(:payload,
              'ARRAY<STRUCT<RunId:STRING,QueryKey:STRING,Latitude:DOUBLE,Longitude:DOUBLE,Confidence:STRING,
              FeatureType:STRING,MatchCodes:ARRAY<STRING>,CalculationMethod:STRING,ResultStatus:STRING,
              Accepted:BOOLEAN,MapAddress:STRING,Province:STRING,District:STRING,Geotype:STRING,ReturnedPostCode:STRING>>')) value)) s
              ON t.RunId=s.RunId AND t.QueryKey=s.QueryKey WHEN NOT MATCHED THEN INSERT
              (RunId,QueryKey,Latitude,Longitude,Confidence,FeatureType,MatchCodes,CalculationMethod,ResultStatus,
               Accepted,MapAddress,Province,District,Geotype,ReturnedPostCode,ProcessedAt)
              VALUES(s.RunId,s.QueryKey,s.Latitude,s.Longitude,s.Confidence,s.FeatureType,s.MatchCodes,
               s.CalculationMethod,s.ResultStatus,s.Accepted,s.MapAddress,s.Province,s.District,s.Geotype,
               s.ReturnedPostCode,current_timestamp())''',{'payload':json.dumps(output)})
            print('Checkpoint:',offset+len(keys),'/',len(pending),dict(Counter(r['ResultStatus'] for r in output)),flush=True)
    results=_query(f'SELECT * FROM {AUDIT} WHERE RunId=:run',{'run':RUN})
    promoted=[]; reviews=[]
    for result in results.to_dict('records'):
        for row in members[result['QueryKey']]:
            if not result['Accepted']:
                reviews.append(dict(Practice=row['PracNumDisplay'],Name=row['PracName'],Category=row['ProviderCategory'],Reason=result['ResultStatus']))
                continue
            promoted.append(dict(PracNum=float(row['PracNum']),SourceAddress=row['DisplayAddress'],
                Latitude=result['Latitude'],Longitude=result['Longitude'],MatchLevel=coordinate_level(result['CalculationMethod']),
                MapAddress=result['MapAddress'],Source='Azure Maps Geocoding 2026-01-01; '+RUN,
                GeocodedAt=result['ProcessedAt'].isoformat()))
    if promoted:
        _query('''MERGE INTO hive_metastore.geomap.ProviderAddressGeocode t USING (
            SELECT value.* FROM (SELECT explode(from_json(:payload,
            'ARRAY<STRUCT<PracNum:DOUBLE,SourceAddress:STRING,Latitude:DOUBLE,Longitude:DOUBLE,MatchLevel:STRING,MapAddress:STRING,Source:STRING,GeocodedAt:TIMESTAMP>>')) value)) s
            ON t.PracNum=cast(s.PracNum AS DECIMAL(10,0))
            WHEN MATCHED AND coalesce(t.MatchLevel,'')<>'Street' THEN UPDATE SET
              t.SourceAddress=s.SourceAddress,t.Latitude=s.Latitude,t.Longitude=s.Longitude,t.MatchLevel=s.MatchLevel,
              t.MapAddress=s.MapAddress,t.Source=s.Source,t.GeocodedAt=s.GeocodedAt
            WHEN NOT MATCHED THEN INSERT (PracNum,SourceAddress,Latitude,Longitude,MatchLevel,MapAddress,Source,GeocodedAt)
              VALUES(cast(s.PracNum AS DECIMAL(10,0)),s.SourceAddress,s.Latitude,s.Longitude,s.MatchLevel,s.MapAddress,s.Source,s.GeocodedAt)''',{'payload':json.dumps(promoted)})
    report=dict(run=RUN,providers=len(rows),eligible=sum(map(len,members.values())),unique_requests=len(queries),
        no_address=invalid,accepted_providers=len(promoted),review=reviews,
        results=results.groupby(['ResultStatus','CalculationMethod'],dropna=False).size().rename('Queries').reset_index().where(lambda f:f.notna(),None).to_dict('records'))
    Path('artifacts/provider_azure_maps_results.json').write_text(json.dumps(report,indent=2,default=str))
    print('Accepted providers:',len(promoted),'Review:',len(reviews),'Missing address:',len(invalid),flush=True)
    print(results.groupby('ResultStatus').size().to_string(),flush=True)


if __name__=='__main__': main()
