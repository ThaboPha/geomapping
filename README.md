# GeoBonalytics / GeoMap

Streamlit application for provider search, member access planning, specialist and hospital alignment, and data quality. Membership lookup is optional. Data comes from Databricks GeoMap views or an explicitly captured private snapshot; the application does not generate demonstration member data.

## Run locally

Use Python 3.13. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r geomap_app/requirements.txt
Copy-Item geomap_app/local-settings.example.json geomap_app/local-settings.json
.\start-app.ps1
```

Edit the local settings to match your authorised Databricks dbt profile and target. Credentials belong in your private dbt profile or environment, never in this repository. Alternatively configure Databricks authentication through environment variables as supported by `geomap_app/geomap/databricks_source.py`.

The four pages cover provider lookup; member access with radius standards, option summaries and district gaps; specialist alignment, discipline gaps and recruitment; and data quality. Coverage depends on available locations, network eligibility and coordinate quality. Approximate area coordinates remain labelled as estimates.

## Snapshot backend

Set `GEOMAP_BACKEND=snapshot` to browse a captured snapshot without Databricks compute. Set `GEOMAP_BACKEND=live` for live queries. Private snapshot data is deliberately excluded from Git. A fresh checkout needs a live connection or a separately provisioned snapshot.

For a manual capture, with authorised live access configured:

```powershell
.\.venv\Scripts\python.exe build_manual_snapshot.py
.\.venv\Scripts\python.exe validate_manual_snapshot.py
.\.venv\Scripts\python.exe validate_snapshot_offline.py
```

The builder publishes to `geomap_app/snapshotdata`. Snapshot mode validates the manifest and checksums and disables personal membership lookup. Refreshes are manual; there is no daily scheduler. See [manual snapshot instructions](MANUAL_SNAPSHOT_TRIAL.md).

## Deployment and checks

See [Azure deployment](azure/README.md). `python azure/package.py` builds the deployment ZIP from an allowlist and includes a locally available validated snapshot. Deployment artifacts and snapshots must be handled privately.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s geomap_app -p 'test_*.py'
.\.venv\Scripts\python.exe -m unittest test_member_azure_maps test_provider_azure_maps
```

SQL definitions are in `geomap_app/sql`. The Azure Maps scripts support reviewed member and provider geocoding; they require separately configured credentials and authorised database access. Generated data, residential addresses, credential files, local environments and operational reports are excluded from version control.
