"""Deploy the additive member pipeline. Log statements by index, never addresses."""
from pathlib import Path
import argparse
parser=argparse.ArgumentParser()
parser.add_argument("--views-only",action="store_true")
args=parser.parse_args()
from live_test import app_dir
from geomap.databricks_source import _query
sql=(app_dir/'sql'/'05_member_population_pipeline.sql').read_text()
# This source has no semicolons inside literals; split the reviewed statements.
sql='\n'.join(line for line in sql.splitlines() if not line.lstrip().startswith('--'))
statements=[part.strip() for part in sql.split(';') if part.strip()]
if args.views_only:
    statements=[statement for statement in statements if statement.startswith('CREATE OR REPLACE VIEW hive_metastore.geomap.') or 'CREATE TABLE IF NOT EXISTS hive_metastore.geomap_private.CoordinateClassification' in statement]
for index, statement in enumerate(statements,1):
    print(f'Applying member pipeline statement {index}/{len(statements)}',flush=True)
    _query(statement)
print('Pipeline deployed',flush=True)
for statement in [
 'SELECT LocationStatus, sum(MemberCount) AS Members, count(*) AS AddressPlanGroups FROM hive_metastore.geomap.MemberLocation GROUP BY ALL',
 'SELECT QueueStatus, sum(Members) AS Members, count(*) AS Addresses FROM hive_metastore.geomap_private.MemberGeocodingQueue GROUP BY ALL',
 'SELECT AssessmentStatus, sum(MemberCount) AS Members FROM hive_metastore.geomap.MemberAccess WHERE ProviderCategory=\'GP\' GROUP BY ALL']:
    print(_query(statement).to_string(index=False),flush=True)
