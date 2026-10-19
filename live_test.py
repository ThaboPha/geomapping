"""Read-only validation of the configured Databricks pages and search controls."""
import json
import os
import sys
import argparse
import time
from pathlib import Path

root = Path(__file__).parent
app_dir = root / 'geomap_app'
for key, value in json.loads((app_dir / 'local-settings.json').read_text()).items():
    os.environ[key] = value
sys.path.insert(0, str(app_dir))

from streamlit.testing.v1 import AppTest
from geomap.databricks_source import _query


def assert_clean(app, page):
    if app.exception:
        raise AssertionError(f'{page}: ' + '; '.join(e.message for e in app.exception))


def member_page(page):
    from geomap import config
    from geomap.databricks_source import DatabricksSource
    number = _query(f"SELECT MIN(memnum) AS n FROM {config.MEMBER_SOURCE} WHERE product_code = 'CLAS'").iloc[0]['n']
    member = DatabricksSource().find_members(str(number)).iloc[0].to_dict()
    test = AppTest.from_string(f'from geomap.views.{page} import render\nrender()')
    test.session_state['active_member'] = member
    test.session_state['membership_checked_at'] = time.time()
    return test.run(timeout=180)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--entry-only', action='store_true')
    args = parser.parse_args()
    app = AppTest.from_file(str(app_dir / 'app.py')).run(timeout=180)
    assert_clean(app, 'entry point')
    if not any(c.value == 'Live Databricks: hive_metastore.geomap' for c in app.sidebar.caption):
        raise AssertionError('The app must identify the real Databricks source')
    print('Entry point: live Databricks source confirmed', flush=True)
    if args.entry_only:
        sys.exit(0)
    for page in ['lookup', 'quality', 'alignment', 'coverage']:
        app = member_page(page)
        assert_clean(app, page)
        print(f'{page}: rendered; {len(app.dataframe)} tables, {len(app.metric)} metrics', flush=True)
        if page == 'lookup':
            app.text_input(key='place_q').set_value('Sandton').run(timeout=180)
            assert_clean(app, 'Sandton lookup')
            assert_clean(app, 'live hospital directory')
            print(f'Live hospital directory: {len(app.dataframe)} result tables', flush=True)
            if not app.dataframe:
                raise AssertionError('Expected real hospital directory records awaiting coordinates')
            next(w for w in app.toggle if 'unverified' in w.label).set_value(False).run(timeout=180)
            assert_clean(app, 'confirmed assignment filter')
            if app.dataframe:
                raise AssertionError('Unknown assignment statuses must be excluded from confirmed results')
            print('Confirmed assignment filter: unknown statuses excluded', flush=True)
            candidate = _query('''SELECT p.ProdCode, pc.Latitude, pc.Longitude
                FROM hive_metastore.geomap.ProductNetworkProvider p
                JOIN hive_metastore.geomap.ProviderMaster pm ON pm.PracNum = p.PracNum
                JOIN hive_metastore.geomap.PlaceCentroid pc
                  ON lower(trim(pc.Place)) = lower(trim(coalesce(nullif(trim(pm.Suburb), ''), pm.Town)))
                 AND pc.PostCode <=> pm.PostCode AND pc.Province <=> pm.ProvinceDescr
                WHERE pm.ProviderCategory = 'Hospital' AND pc.Latitude IS NOT NULL
                  AND trim(p.ProdCode) = 'CLAS' LIMIT 1''').iloc[0]
            next(w for w in app.toggle if 'unverified' in w.label).set_value(True)
            next(w for w in app.toggle if 'approximate place' in w.label).set_value(True)
            app.segmented_control(key='loc_mode').set_value('Coordinates').run(timeout=180)
            next(w for w in app.number_input if w.label == 'Latitude').set_value(float(candidate.Latitude))
            next(w for w in app.number_input if w.label == 'Longitude').set_value(float(candidate.Longitude))
            app.run(timeout=180)
            assert_clean(app, 'provisional coordinate lookup')
            if len(app.dataframe) < 2:
                raise AssertionError('Expected approximate candidates and the unmapped directory')
            results = app.dataframe[0].value
            if not (results['Location accuracy'] == 'Provisional place centroid').any():
                raise AssertionError('Approximate locations must be labelled as provisional centroids')
            print('Opt-in approximate locations: real centroid match with explicit accuracy label', flush=True)
