from live_test import app_dir
from geomap.databricks_source import _query
sql=(app_dir/'sql'/'06_member_access_planning.sql').read_text()
sql='\n'.join(line for line in sql.splitlines() if not line.lstrip().startswith('--'))
for statement in sql.split(';'):
    if statement.strip():
        _query(statement)
print('Planning views deployed',flush=True)
print(_query('SELECT Geotype,sum(MemberCount) AS Members FROM hive_metastore.geomap.MemberLocation GROUP BY Geotype').to_string(index=False),flush=True)
from geomap.data import get_source
hist=get_source().access_histogram(planning=True)
print('Planning histogram rows:',len(hist),flush=True)
from streamlit.testing.v1 import AppTest
app=AppTest.from_string('from geomap.views.member_population import render\nrender()')
app.session_state['member_area_planning']=True
app.run(timeout=180)
assert not app.exception,[e.message for e in app.exception]
print('Planning standard and gaps page passed',flush=True)
