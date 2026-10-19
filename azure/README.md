# Azure App Service

Use a Linux App Service with Python 3.13, startup command `sh startup.sh`, and `SCM_DO_BUILD_DURING_DEPLOYMENT=true`. Enable Always On and configure the health check at `/_stcore/health`. Protect member analytics with organisation authentication before making the app available.

Run `python azure/package.py` from the repository root. The allowlisted package excludes local settings and credentials and includes a complete, checksum-validated snapshot when one is present locally. The output is `artifacts/geobonlytics.zip`; keep this artifact private because it can contain business data.

Configure `GEOMAP_MODE=databricks`, `GEOMAP_CATALOG=hive_metastore`, and `GEOMAP_SCHEMA=geomap`. Choose `GEOMAP_BACKEND=snapshot` to serve a separately captured snapshot without Databricks compute, or `GEOMAP_BACKEND=live` for live database queries. Live mode needs authorised Databricks credentials in App Service settings or Key Vault references, and available compute. Do not deploy a dbt profile or `local-settings.json`.

For an existing authenticated App Service:

```powershell
az webapp deploy --resource-group <resource-group> --name <app-name> --src-path artifacts/geobonlytics.zip --type zip
```

Validate health and authenticated navigation after deployment. In snapshot mode, also check the displayed capture date and all four pages. In live mode, verify a real data query; a healthy web process alone does not establish database access. Ordinary code updates do not require creating new credentials.
