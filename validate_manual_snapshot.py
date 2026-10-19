"""Check live parity, then render pages with every SQL call deliberately blocked."""
import json
import os
from pathlib import Path
import time
from unittest.mock import patch
import pandas as pd
from pandas.testing import assert_frame_equal

from live_test import app_dir
from geomap.snapshot_source import SnapshotSource
from geomap.databricks_source import DatabricksSource
from geomap.data import get_source
from streamlit.testing.v1 import AppTest

source=SnapshotSource(app_dir/'snapshotdata')
expected=source._read('network_expected')
actual=source.network_directory()
columns=list(expected.columns)
assert_frame_equal(actual[columns].sort_values('PracNum').reset_index(drop=True),expected.sort_values('PracNum').reset_index(drop=True),check_dtype=False)
live=DatabricksSource()
scenarios=[('Core Specialist',None,False,True),('Hospital',None,False,False),('GP',None,True,True),('Unclassified',72,False,True)]
for category,code,planning,all_providers in scenarios:
    args=('STD',-25.722,28.183,category,code,200,50)
    before=live.providers_near(*args,include_unverified=True,use_place_centroids=planning,all_providers=all_providers)
    after=source.providers_near(*args,include_unverified=True,use_place_centroids=planning,all_providers=all_providers)
    assert list(before.PracNumDisplay)==list(after.PracNumDisplay),(category,'provider identities/order differ')
    if len(before):
        assert max(abs(before.DistanceKm.to_numpy()-after.DistanceKm.to_numpy()))<0.000001
    print('Live/snapshot search parity:',category,planning,all_providers,len(after),flush=True)

get_source.clear()
timings={}
with patch('geomap.config.DATA_BACKEND','snapshot'),patch('geomap.databricks_source._query',side_effect=AssertionError('SQL disabled during offline verification')) as sql,patch('geomap.databricks_source._connection',side_effect=AssertionError('No compute connection permitted')):
    start=time.perf_counter()
    app=AppTest.from_file(str(app_dir/'app.py')).run(timeout=30)
    assert not app.exception,[e.message for e in app.exception]
    assert any('Snapshot data' in message.value for message in app.sidebar.info)
    assert not any('Membership number' in item.label for item in app.text_input)
    timings['entry']=time.perf_counter()-start
    for name in ('alignment','quality','coverage'):
        start=time.perf_counter()
        app=AppTest.from_string(f'from geomap.views.{name} import render\nrender()').run(timeout=30)
        assert not app.exception,[e.message for e in app.exception]
        timings[name]=time.perf_counter()-start
        if name=='coverage':
            start=time.perf_counter()
            app.slider[0].set_value(15).run(timeout=30)
            assert not app.exception
            timings['radius_change']=time.perf_counter()-start
            app.toggle(key='member_area_planning').set_value(True).run(timeout=30)
            assert not app.exception
    app=AppTest.from_string('from geomap.views.lookup import render\nrender()').run(timeout=30)
    app.text_input(key='place_q').set_value('Capital Park').run(timeout=30)
    assert not app.exception,[e.message for e in app.exception]
    assert source.search_places('capital park').shape[0]>0
    sql.assert_not_called()
    print('All offline pages and filters passed with SQL explicitly blocked.',flush=True)
get_source.clear()
print('Local page timings (seconds):',timings,flush=True)
Path('artifacts/snapshot_validation.json').write_text(json.dumps(dict(snapshot=source.manifest['version'],
    datasets=len(source.manifest['datasets']),total_bytes=sum(e['bytes'] for e in source.manifest['datasets'].values()),
    sql_disabled_tests_passed=True,live_search_parity_passed=True,local_seconds=timings),indent=2))
