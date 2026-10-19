"""Download official boundaries, classify existing points locally, store linkage only."""
import json
from pathlib import Path
import argparse
parser=argparse.ArgumentParser()
parser.add_argument("--settlement-geojson",type=Path)
args=parser.parse_args()
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from live_test import app_dir
from geomap.area_classification import classify_point, metro_distance_km, distance_area
from geomap.databricks_source import _query

base='https://nspdr.dlrrd.gov.za/server/rest/services/NationalDatasets/MunicipalDemarcationBoard/MapServer/'
cache=app_dir/'geographic_reference'
cache.mkdir(exist_ok=True)
layers={}
for name,layer in [('municipalities',3),('provinces',5)]:
    path=cache/(name+'.geojson')
    if path.exists():
        data=json.loads(path.read_text())
    else:
        def request(options):
            with urlopen(base+str(layer)+'/query?'+urlencode(options),timeout=60) as response:
                payload=json.load(response)
            if 'error' in payload:
                raise RuntimeError(str(payload['error']))
            return payload
        ids=request(dict(where='1=1',returnIdsOnly='true',f='json'))['objectIds']
        data={'features':[]}
        for offset in range(0,len(ids),10):
            page=request(dict(objectIds=','.join(map(str,ids[offset:offset+10])),outFields='*',returnGeometry='true',outSR=4326,f='json'))
            data['features'].extend(page.get('features',[]))
        if len(data['features'])!=len(ids):
            raise RuntimeError('Incomplete public boundary download')
        data['features']=[dict(properties=f['attributes'],geometry=dict(type='EsriPolygon',rings=f['geometry']['rings'])) for f in data['features']]
        path.write_text(json.dumps(data),encoding='utf-8')
    layers[name]=data['features']
    print('Downloaded official '+name+': '+str(len(data['features']))+' features',flush=True)
# Fetch coordinates internally; no member location is sent to the public service.
points=_query('SELECT DISTINCT Latitude,Longitude FROM hive_metastore.geomap_private.AddressGeocode WHERE Status=\'MATCHED\' AND Latitude IS NOT NULL AND Longitude IS NOT NULL')
_query('''CREATE TABLE IF NOT EXISTS hive_metastore.geomap_private.CoordinateClassification
    (Latitude DOUBLE,Longitude DOUBLE,Province STRING,District STRING,Geotype STRING,
     Source STRING,ClassifiedAt TIMESTAMP) USING DELTA''')
settlements=None
if args.settlement_geojson:
    settlement_payload=json.loads(args.settlement_geojson.read_text(encoding='utf-8'))
    settlements=settlement_payload['features']
    if any(f.get('properties',{}).get('Geotype') not in {'Urban','Rural'} for f in settlements):
        raise ValueError('Settlement reference must explicitly label every feature Urban or Rural.')
    if not settlement_payload.get('source'):
        raise ValueError('Settlement reference must include its official source URL as top-level source.')
classified={}
rows=[]

for point in points.itertuples():
    result=classify_point(float(point.Longitude),float(point.Latitude),layers['municipalities'],layers['provinces'],settlements)
    distance=metro_distance_km(float(point.Longitude),float(point.Latitude),layers['municipalities'])
    result['Geotype']=distance_area(distance)
    province_alias={'Kwazulu-Natal':'KwaZulu-Natal','Northern Province':'Limpopo'}
    result['Province']=province_alias.get(result['Province'],result['Province'])
    row=dict(Latitude=float(point.Latitude),Longitude=float(point.Longitude),**result,
        Source=base+'3;'+base+'5; USER_DISTANCE_RULE: metro boundary <10km Metro, 10-<40km Urban, >=40km Rural; approximate ground distance')
    rows.append(row)
    classified[result['Geotype']]=classified.get(result['Geotype'],0)+1
for offset in range(0,len(rows),50):
    _query('''MERGE INTO hive_metastore.geomap_private.CoordinateClassification target
       USING (SELECT value.* FROM (SELECT explode(from_json(:payload,
         'ARRAY<STRUCT<Latitude:DOUBLE,Longitude:DOUBLE,Province:STRING,District:STRING,Geotype:STRING,Source:STRING>>')) AS value)) source
       ON target.Latitude=source.Latitude AND target.Longitude=source.Longitude
       WHEN MATCHED THEN UPDATE SET target.Province=source.Province,target.District=source.District,
         target.Geotype=source.Geotype,target.Source=source.Source,target.ClassifiedAt=current_timestamp()
       WHEN NOT MATCHED THEN INSERT (Latitude,Longitude,Province,District,Geotype,Source,ClassifiedAt)
         VALUES (source.Latitude,source.Longitude,source.Province,source.District,source.Geotype,source.Source,current_timestamp())''',{'payload':json.dumps(rows[offset:offset+50])})
print('Coordinate classification counts:',classified,flush=True)
