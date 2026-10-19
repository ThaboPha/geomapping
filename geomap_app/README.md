# Bonitas network geo-mapping app

A Streamlit app for directing members to network providers and for planning network access.
It uses real Databricks GeoMap views, directly or through the private snapshot backend.

For current setup and snapshot operation, start with the [repository README](../README.md)
and [manual snapshot instructions](../MANUAL_SNAPSHOT_TRIAL.md). The dated validation
notes below describe earlier live-data checks and are not current inventory totals.

## Pages

| Page | Who uses it | What it does |
|---|---|---|
| Find a provider | Members, call centre | Optional membership lookup, or suburb search with a manually selected benefit option; live location and coordinates also supported |
| Member access | Members, Provider Networks | Selected suburb/location access, provider availability curves, radius scenarios, option and discipline gaps, and CSV export without member population tables |
| Specialists and hospitals | Provider Networks | Specialist-to-network-hospital alignment, hospitals missing core disciplines, recruitment targets |
| Data quality | Provider Networks, data team | Address flags, geocode accuracy, data freshness |

## Run locally (live Databricks)

On this Windows machine, double-click `start-app.cmd` in the parent folder, or run
`.\start-app.ps1` from that folder. Open http://localhost:8501 after startup.
The launcher prefers the local `.venv313` environment (Python 3.13.14), falling back
to `.venv` if it is absent, and loads the app's theme. Python 3.14.4 crashed during
browser navigation testing, so this laptop now uses the Python 3.13 environment.
`constraints-runtime.txt` records the native-library versions used in that environment.
Databricks connection retries are bounded, and a busy query lock returns an error
instead of waiting indefinitely. Temporary DNS/connection failures block live lookup
without substituting cached membership or demo data.
It now loads `local-settings.json`, which connects to the existing `databricks/dev`
dbt profile and reads `hive_metastore.geomap`. Credentials stay in your existing
`~/.dbt/profiles.yml`; they are not copied into the app.

Only `GEOMAP_MODE=databricks` is supported. Other values are rejected.

For a fresh installation, create a virtual environment in the parent folder and install
`geomap_app/requirements.txt` with its Python interpreter. Alternatively, from this
`geomap_app` folder with Python available on PATH:

```bash
pip install -r requirements.txt
streamlit run app.py
```

Running `app.py` directly also requires a live Databricks connection. The Windows
launcher loads the local connection settings. Missing data or failed connections
produce a clear message; the app never substitutes synthetic records.

## Connected live sources

The existing views created by the health medallion project are used directly:
`ProviderMaster`, `ProductNetworkProvider`, `PracticeGeocode`, `ProviderCategory`,
`AccessStandard`, `PlaceCentroid`, `ProductOption`, and `SpecialistHospitalAlignment`
in `hive_metastore.geomap`. No source views are changed by this application.

Live validation found 99,759 active practices, 14 product options, and 136 network
providers on 13 October 2026. All 136 network providers currently lack valid provider
coordinates; assignment-block status is unavailable on all 529 network relationships.
The app shows these as unverified directory candidates awaiting coordinates.
Disabling unverified candidates excludes unknown statuses from the results.

Choose **All active providers** under **Provider directory** to search the full
`ProviderMaster` view, rather than only the benefit option's network relationships.
Both searches join `PracticeGeocode` on `PracNum` and display `ProviderMaster.DisplayAddress`.
Providers without a relationship to the selected option are labelled
**Cover not confirmed for selected option**. The current full view has 2,368 valid
coordinate records; none of the 136 network providers have coordinates, including
their alternate source addresses. The connected workspace exposes `geomap`, not
`geomapp`; configure another catalog/schema only after verifying that source exists.

For approximate mapping, explicitly enable **Use approximate place locations for
unmapped providers**. This matches the provider's suburb/town, postcode and province
to the existing provider-derived `PlaceCentroid` view. Matches use the label
**Provisional place centroid** and do not represent the provider's premises.
The source snapshot had matching place centroids for 59 of the 136 network providers.

Membership number is optional on every page. Start on Find a provider, select a suburb and benefit option, then open Member access, Specialists and hospitals, or Data quality. Analytics default to all options; selected-option scopes can be used without membership. The app reads active
beneficiaries from `hive_metastore.care_coordination_reporting.vw_member_current`,
using the existing current subscription and beneficiary joins over `membership_live`.
The membership lookup retrieves number, beneficiary number/role, scheme and product;
the selected beneficiary's current registered address is fetched separately. Names and
medical records are not retrieved. Choose a beneficiary
where needed. The benefit option is fixed to that record. Changing membership or
beneficiary clears the previous location and provider address matches and loads that
beneficiary's registered address. Membership is
rechecked after five minutes; unavailable or inactive membership clears the personalised context and allows general browsing.

Suburb search is the default without membership. Registered address is the default when a membership is loaded. Address selection excludes future effective
versions, prefers residential/street records, then postal records, and uses the account
address if the beneficiary has none. The address source/type is displayed. Only registered
locality/postcode terms are sent to Photon; member IDs and street lines are not sent or
stored in the shared geocoder cache. These are explicitly labelled area estimates, with
postal-address warnings. No default coordinate is invented if lookup fails or is ambiguous.
Live location and typed address searches override this default until the user returns to
Registered address or changes beneficiaries. Search choices survive page navigation.

Member Access uses the registered default or the search location chosen on Find a provider. It does not invent
member coordinates or population coverage statistics. Standards remain proposed,
not approved. A membership number identifies a benefit record; it is not identity
authentication. Patient identity verification is required before exposing personal or
clinical records in a public deployment.

Specialists/hospitals defaults to the selected member's product relationships. Nearest
hospital alignment is recomputed within that option. All network options is available for
planning using the existing shared-option source view. Hospitals without coordinates remain
visible in directories and exports. Missing-coordinate discipline pairs are unassessed,
not confirmed gaps. Street accuracy is required before claiming an on-site match.

Data quality supports member-option/all-source scope, category/province filters, valid
coordinate counts, charts, address remediation, and full backlog/summary CSV downloads.
Directories, alignment, discipline coverage and directions have also been restored from
the ZIP. Directions offer driving, transit and walking, and share coordinates with Google
Maps only when opened.

Population planning retains the ZIP's radius controls and proposal CSV. The connected
GeoMap schema currently lacks `MemberLocation` and `MemberAccess`, so measured coverage
curves, percentages and district gaps are unassessed. Active beneficiary/account/locality
counts come from the live member view. Proposal exports use blank coverage values until
real measured data exists; no demo records or assumed area classifications are used.

From the project root, run `.\.venv\Scripts\python.exe check_databricks.py` for a
read-only source inventory, or `.\.venv\Scripts\python.exe membership_live_test.py`
to check optional membership, benefit option selection and pages against live data.
Run `requested_member_live_test.py` and `browser_requested_member_test.py` from the root
to verify member 6683681, dependant defaults, tab controls, location overrides and exports.

## Patient location search

Click **Use my live location** and allow your browser's location request. The app
populates latitude and longitude and searches using your member's benefit option and
provider type. Click again to refresh your position and recenter the map, even if
the device returns the same coordinates. **Recenter map on my search location**
restores the view after panning. The red dot and label mark the selected search
point; the pale red circle shows the device's estimated accuracy. Panning the map
does not change your search coordinates. This is a single location
capture, not continuous tracking. Coordinates are sent to the app and Databricks to
calculate distances; the app does not write patient location records to the database.

Location sharing is optional. Patients can enter their suburb or postcode instead.
Permission denial, timeout, unsupported browsers, invalid coordinates and locations
outside the supported South African bounds produce a message with that fallback.
A failed refresh preserves the previous search and explicitly says it was not refreshed.
The app retries coarse readings for up to 30 seconds and keeps the most accurate
reading in that attempt. It stops early at a reported accuracy of 100 metres or better.
The device's estimated accuracy is displayed, with an additional message above 1 km.
A laptop can return the wrong town even with a small reported accuracy. Check the
red dot and use suburb/postcode search when it does not represent your actual area.
Captured coordinates do not imply a verified Metro, Urban or Rural classification.

The address directory has a **Directory province** filter. Its initial province is
suggested from the nearest available place centroid within 75 km; confirm or change
it when the browser's position is wrong. This is a province address filter, not a
distance ranking. **Refresh live provider data** clears query caches and rereads
the current GeoMap views. Results are otherwise cached for up to 30 seconds;
upstream provider coordinates and ingestion must still be supplied by the data source.

Local testing works at `http://localhost:8501`. When patients use the app from other
devices, serve it over HTTPS and allow geolocation in any embedding permissions policy;
plain HTTP on a LAN IP does not provide a secure browser location context.
See [browser geolocation requirements](https://developer.mozilla.org/en-US/docs/Web/API/Geolocation/getCurrentPosition).

Location test commands from the project root:

```powershell
.\.venv\Scripts\python.exe geomap_app\test_location.py
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PWD '.browser-cache'
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe browser_location_test.py
```

Browser checks run against the live Databricks app and use simulated device locations.
They cover granted/denied browser permissions, coordinate population, refresh, manual
edits, search filters, suburb fallback, unsupported/insecure contexts, invalid/out-of-region
locations, errors and retries, late responses, and a 390 px mobile layout.

## Deploy to Databricks Apps

1. **Use the existing views** in `hive_metastore.geomap`, maintained by the health medallion
   project's `databricks/geomap/01_create_geomap_realtime_views.sql`.
2. Confirm the deployment principal can read those views and their underlying provider
   sources. `PlaceCentroid` and `ProductOption` already exist. The SQL Server landing
   script in `sql/databricks_setup.sql` is an alternative setup, not needed here.
3. **Create the app** in the workspace (Compute → Apps → Create app → Custom) and add a
   **SQL warehouse** resource with key `sql-warehouse` and permission *Can use*.
4. **Grant** the app's service principal the applicable schema/view and underlying-source
   read permissions for your workspace's metastore configuration.
5. **Deploy** the code:
   ```bash
   databricks sync . /Workspace/Users/<you>/geomap-app
   databricks apps deploy <app-name> --source-code-path /Workspace/Users/<you>/geomap-app
   ```
6. Edit `app.yaml` if your catalog or schema names differ.

## Configuration (`app.yaml` / environment)

| Variable | Default | Purpose |
|---|---|---|
| `GEOMAP_MODE` | `databricks` | Only live Databricks is supported |
| `GEOMAP_CATALOG` / `GEOMAP_SCHEMA` | `bonitas_geo` / `geomap` | Where the tables live |
| `DATABRICKS_WAREHOUSE_ID` | from resource | SQL warehouse used for queries |
| `DATABRICKS_HTTP_PATH` | empty | Existing SQL warehouse or cluster SQL endpoint |
| `GEOMAP_DBT_PROFILE` / `GEOMAP_DBT_TARGET` | empty | Local dbt connection; launcher selects `databricks` / `dev` |
| `GEOMAP_PLACE_TABLE` | `PlaceCentroid` | Suburb/postcode centroids |
| `GEOMAP_OPTION_TABLE` | `ProductOption` | Option display names |
| `GEOMAP_MEMBER_CATALOG` / `GEOMAP_MEMBER_SCHEMA` | `hive_metastore` / `care_coordination_reporting` | Current active membership source |
| `GEOMAP_CURRENT_MEMBER_TABLE` | `vw_member_current` | Required current-beneficiary view |
| `GEOMAP_CACHE_TTL` | `30` | Seconds to cache query results |

## Structure

```
app.py                      entry point and navigation
app.yaml                    Databricks Apps config
geomap/config.py            settings and table names
geomap/data.py              DataSource interface (all pages use this)
geomap/databricks_source.py Unity Catalog queries (parameterised)
geomap/geo.py               haversine distance and bounding box
geomap/views/               one module per page
sql/databricks_setup.sql    Unity Catalog tables and grants
```

## Known gaps

- **Practice telephone number** is not in ProviderMaster yet. Add it to Script 01, then to the
  lookup table in `views/lookup.py`.
- **Address and suburb search** uses real OpenStreetMap / Photon results, rather than
  provider-derived place centroids. Search text is sent to the configured service;
  users must confirm the match and should omit names and medical details. Configure
  `GEOMAP_GEOCODER_URL` for a hosted Photon instance before substantial production use.
  The public service permits reasonable use but provides no availability guarantee:
  [Photon service documentation](https://github.com/komoot/photon#demo-server).
- **Missing practice coordinates** remain a source-data gap. Patients can explicitly
  search a listed provider's public address, choose a match and show it in blue.
  Such matches are labelled for premises confirmation and kept in the current
  session; the app does not write them back as verified Databricks coordinates.
  Address-only entries without a confirmed map match have no marker.
- **Population coverage** still requires a verified member-location dataset. Personal Member Access uses the member's chosen search location and live network option instead.
- **Admitting behaviour** (claims lens) is not yet included in the alignment page.

## Location standards and gaps

Member access uses the location selected on Find a provider. Test a standard compares live option networks by provider type, discipline and province, using Metro / Urban / Rural radii as scenarios at that same location. Charts count providers within distance, not members. Missing provider coordinates produce unresolved results rather than confirmed geographic gaps. The optional provider suburb estimate uses source place centroids and is explicitly provisional. No MemberAccess table or membership record is needed for this workflow.

## Member population layout

The Member access page restores the original ZIP layout: radius sliders, member coverage curves, By option, and province/district/area gaps. It reads the configured MemberAccess source when available and requires no entered membership number. The current live schema has no member coverage table, and vw_member_current lacks province, district, area classification and coordinates. Missing member totals and percentages remain unavailable rather than being inferred from provider counts. The separate location-based provider tests remain in expandable sections beneath this layout.

Member population fallback now reads current profiles and subscriptions from membership_live directly, with registered beneficiary addresses and account-address fallbacks. Only aggregate counts leave Databricks. By option shows real beneficiary totals and plan shares; the locality table shows percentages within each filtered plan. Province matches require an unambiguous locality/postcode reference match. Unknown province, district and area classifications are retained; missing distance coverage remains blank. This source differs from vw_member_current, which reads membership_latest.

## Deployed member population pipeline

`sql/05_member_population_pipeline.sql` creates the missing objects from current
`membership_live` profiles, subscriptions and effective addresses:

- `geomap_private.MemberAddressPopulation`: address groups and beneficiary counts,
  with no member identifiers or names.
- `geomap_private.AddressGeocode`: persistent geocoder result and source metadata.
- `geomap_private.MemberGeocodingQueue`: distinct residential addresses awaiting a
  result; postal, missing and unsupported-country addresses remain separate.
- `geomap.MemberLocation`: aggregate address/plan location counts and readiness.
- `geomap.MemberAccess`: weighted location/plan/type/discipline distances and status.

Existing source tables remain unchanged. Access permissions on the private schema
must follow the organisation's existing member-address access policy; the app does
not read street address fields from it. No grants are broadened by this deployment.
Address hashes are linkage keys, not a claim of anonymisation.

Current internal reference matching supplies provisional area coordinates only,
using an exact registered town/postcode and an unambiguous source reference point.
It does not assign districts or Metro/Urban/Rural classifications. Residential
addresses with complete approved geography become ready; other records retain
explicit statuses. Targets with missing provider coordinates remain unassessed.
The app sums MemberCount rather than counting address groups and excludes
unassessed records from measured coverage denominators.

Rerun `deploy_member_pipeline.py` to refresh internal reference matches. Current
membership is read through live views; geocodes are retained under address keys,
so changed addresses do not reuse the old address's coordinates.

An approved geocoder or internal geocoding installation is still needed for unmatched
addresses. Import validated results using `import_member_geocodes.py results.csv`
(dry run), then add `--apply` to load them. The template is
`sql/member_geocode_import_template.csv`. Missing administrative classification
must remain Unknown. The importer requires no member numbers or names, validates
coordinates, precision and source metadata, and checks all address keys before
modifying results. It never sends residential addresses to a public API.

The earlier `04_build_member_access_databricks.sql` is a legacy per-beneficiary
reference and is superseded by the weighted pipeline. Do not execute both.

## Verified geography versus ZIP examples

The supplied Geo-Mapping.zip uses demo.py to generate 8,000 fictional members,
random provider locations, and manually assigned town-level area labels. Those
percentages are examples rather than live benchmarks.

`classify_member_geography.py` downloads all official municipality/province
features from the government NSPDR MunicipalDemarcationBoard GIS service, then
classifies existing coordinates locally. No member points or addresses are sent
to that service. Municipal category A identifies Metro. It assigns an explicit
district/province and retains the source. Urban/Rural requires an explicit
settlement polygon layer: pass `--settlement-geojson path.geojson`, with a
FeatureCollection containing top-level `source` (official URL) and each polygon's
`properties.Geotype` set to Urban or Rural. Non-metropolitan areas are never
implicitly treated as rural. Cached boundary files are under geographic_reference;
source feature timestamps are retained in those files.

CoordinateClassification feeds MemberLocation through exact coordinate joins.
Provisional provider-derived member area centroids remain explicitly unverified,
even when their administrative boundary classification is known. The page shows
member geography counts independently of measured provider coverage. Unclassified
records and missing coordinates remain in the population denominator/report.

The current available inputs cannot yield fully verified Metro/Urban/Rural access
percentages: member residential geocodes, an explicit settlement reference, and
usable network-provider coordinates are still required. Import approved geocodes
through the existing validated importer; the views then evaluate readiness and
coverage automatically.

## User-defined distance classification

The active area rule is now distance from the nearest metropolitan municipality
boundary: inside or <10 km is Metro; 10 to <40 km is Urban; >=40 km is Rural.
This supersedes the earlier settlement-only classification rule and is a
user-defined planning policy, not a Stats SA settlement designation. Boundary
coordinates are downloaded publicly and member coordinates stay internal.
Distance is approximated using local ground projection to the boundary followed
by haversine distance; area centroids remain approximate.

The Member access toggle `Use available area coordinates for planning` reads
MemberAccessPlanning. It uses matched provider area coordinates where source
geocodes are missing, while excluding unresolved targets from coverage
denominators. Verified-only mode continues to use MemberAccess. Access sliders
change provider distance standards independently of the 10/40 km area rule.
`sql/06_member_access_planning.sql` deploys the planning views.

## Capital Park member-access correction

Member geography coverage and readiness cards have been removed from the main
page, leaving the ZIP's standard sliders, three coverage metrics, curve, By option
and district gap tables. Planning mode now evaluates current provider-product
links directly, rather than the narrower network-flagged view (which exposed
only one GP across two products). These are product-linked directory candidates,
not confirmed network eligibility. Provider coordinates use available source
geocodes or exact locality/postcode/province area matches. Percentages and
distance gaps are estimates over mapped members/providers; missing providers
can make reported distance gaps larger than the true gap.

Missing product/network directory entries are no longer counted as measured 0%
coverage in the app histogram. Verified mode remains separate. Member geography
and provider radius calculations are independent of the one suburb chosen on
Find a provider; that location is carried through for location-based searches,
not substituted for every member's residence.

Photon timeout fallback for public searches uses the rate-limited Nominatim
endpoint; registered member area requests do not use this public fallback path.
Capital Park lookup was reproduced against real OpenStreetMap data.

## Specialists and hospitals: original ZIP layout with live coordinates

The tab follows the ZIP section order: province/discipline selectors, four metrics,
stacked alignment chart, map, core-discipline gaps and recruitment targets.
Directories and exports are in a collapsed section below. Membership is optional.
`sql/07_provider_location.sql` exposes live ProviderLocation and ProviderGeocodingQueue
views without overwriting source geocodes. Valid source coordinates take precedence,
then conservatively matched public practice addresses whose source address is
unchanged, then exact unambiguous locality/postcode/province centroids.

`geocode_network_providers.py` performs a single-threaded, rate-limited pass over
public hospital/specialist practice addresses. It never processes member addresses.
Province, locality, street/building tokens and ambiguity checks constrain matches.
Results are stored in ProviderAddressGeocode with address provenance and an
unverified-premises match level. Unmatched addresses remain unlocated.

ProviderAlignmentSource retains actual network/product relationships and calculates
the nearest hospital on shared options. Nearby percentages use assessed pairs only;
the stacked chart also shows unresolved specialists. The more-than-5-km metric is
a count, as in the ZIP. On-site and recruitment require verified street coordinates
and are not asserted from area or public-address estimates. Core-discipline gaps
now check every eligible hospital within 5 km, not only the specialist's nearest
hospital; missing coordinates remain unassessed.
