from live_test import app_dir
from geomap.databricks_source import _query
sql=(app_dir/'sql'/'07_provider_location.sql').read_text()
sql='\n'.join(line for line in sql.splitlines() if not line.lstrip().startswith('--'))
for part in sql.split(';'):
    if part.strip(): _query(part)
print(_query('SELECT ProviderCategory,count(*) AS Providers,count_if(Latitude IS NOT NULL AND Longitude IS NOT NULL) AS Located FROM hive_metastore.geomap.ProviderLocation WHERE IsNetworkProvider=1 GROUP BY ProviderCategory').to_string(index=False),flush=True)
