"""Repeatable presentation smoke check with SQL and external place lookup blocked."""
import os
os.environ['GEOMAP_BACKEND']='snapshot'
from pathlib import Path
import sys
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent/'geomap_app'))
from geomap.data import get_source
from streamlit.testing.v1 import AppTest

get_source.clear()
with patch('geomap.databricks_source._query',side_effect=AssertionError('SQL unavailable')) as queries,patch('databricks.sql.connect',side_effect=AssertionError('Compute unavailable')),patch('geomap.views.lookup.search_places',side_effect=AssertionError('External location service unavailable')):
    for page in ('lookup','coverage','alignment','quality'):
        start=time.perf_counter()
        app=AppTest.from_string(f'from geomap.views.{page} import render\nrender()').run(timeout=30)
        assert not app.exception,[e.message for e in app.exception]
        if page=='lookup':
            app.text_input(key='place_q').set_value('Capital Park').run(timeout=30)
            assert not app.exception,[e.message for e in app.exception]
            location=app.session_state['search_location']
        print(f'{page}: {time.perf_counter()-start:.3f}s; SQL disabled',flush=True)
    app=AppTest.from_string('from geomap.views.coverage import render\nrender()')
    app.session_state['search_location']=location
    start=time.perf_counter(); app.run(timeout=30)
    assert not app.exception,[e.message for e in app.exception]
    print(f'coverage with Capital Park provider scenarios: {time.perf_counter()-start:.3f}s; SQL disabled',flush=True)
    queries.assert_not_called()
print('Snapshot pages pass without Databricks or external Capital Park lookup.',flush=True)
