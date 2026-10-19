# Manual snapshot trial

The app can use a manually captured version of real Databricks results without connecting to Databricks while browsing. There is no scheduler or new Azure storage service in this trial. The approximately 13.3 MB snapshot is packaged privately with the existing authenticated App Service. It survives application restarts and does not depend on an in-memory SQL cache remaining warm.

`GEOMAP_BACKEND=snapshot` selects the snapshot explicitly. `GEOMAP_BACKEND=live` selects the original live source. An incomplete or corrupt snapshot raises a clear error rather than quietly starting a Databricks connection or substituting made-up results. The packaged manifest supplies the visible snapshot timestamp, capture interval, dataset row counts and SHA-256 checksums.

The snapshot contains public provider-directory fields, network relationships, reference data, quality results and precomputed member coverage/readiness aggregates. It excludes membership numbers, beneficiary records, member address keys and residential address lines. Personal membership lookup is disabled in snapshot mode. Provider eligibility/network/coordinate-quality labels remain intact and describe the captured version; cover must still be confirmed with the scheme.

All four pages operate from the snapshot. Radius sliders and filters run locally. The reference locations include a real cached Capital Park OpenStreetMap search. Other suburbs can use the stored locality reference or independent public location search; map tiles and uncached external place searches still require internet connectivity. Neither requires Databricks compute.

Validation for this first trial:

- All 21 datasets are complete and checksum-validated.
- The reconstructed network directory matched the exported live directory.
- Four provider search scenarios matched live provider identities/order and distances (tolerance 0.000001 km): core specialists, hospitals, GP planning estimates and physiotherapy.
- All pages and a radius-slider change passed with SQL explicitly blocked; Capital Park lookup also passed with the external location service blocked.
- 46 application tests passed, including rejected incomplete snapshots, path traversal checks and disabled personal-member lookup.
- Local initial app load: 3.73 s; alignment 1.66 s; quality 1.42 s; member access 1.11 s; radius change 0.11 s. These are local validation timings, not a guarantee of Azure/browser response time.

Aggregate validation results: `artifacts/snapshot_validation.json`. No shared Databricks cluster was stopped for testing.

The trial is deployed to https://geobonlytics.azurewebsites.net with `GEOMAP_BACKEND=snapshot`. The deployed archive manifest was inspected and contained the complete 21-dataset version `20261019T094338Z`. After activation, health returned `200 ok` and browser requests still redirected to Microsoft tenant sign-in. The offline check additionally exercised Member access with Capital Park selected, including provider scenarios, in approximately 3 seconds with SQL blocked.

## Perform another manual refresh

1. Make Databricks compute available. Run `.\.venv313\Scripts\python.exe -u build_manual_snapshot.py`. This starts a **fresh** capture; use `--resume` only to continue an interrupted capture. A failed build preserves the prior published local snapshot. Previous captures are retained for review.
2. Run `.\.venv313\Scripts\python.exe -u validate_manual_snapshot.py` to compare searches with live data and exercise snapshot pages. Run `.\.venv313\Scripts\python.exe -u validate_snapshot_offline.py` to repeat the offline check without live credentials/compute.
3. Run `.\.venv313\Scripts\python.exe azure/package.py`, then deploy the ZIP to the existing App Service. The package validates snapshot file hashes and excludes local settings and credentials.

Deployment command: `az webapp deploy -g rg-lakehouse-AA-Dev-zanorth -n geobonlytics --src-path artifacts/geobonlytics.zip --type zip`.

Reloading a view only reloads the snapshot; it never starts a refresh job or compute. Changes in Databricks become visible only after another capture is validated and deployed. The manifest records individual dataset capture times: this pilot is a capture interval of evaluated live views, not a transactional/time-travel read of every source at one instant. A daily refresh pipeline and separately managed private storage can follow after validation.
