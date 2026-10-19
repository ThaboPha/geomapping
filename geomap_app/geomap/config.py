"""Configuration, read from environment variables (set in app.yaml on Databricks)."""
import os
import re

_IDENT = re.compile(r"^[A-Za-z0-9_]+$")


def _ident(name: str, value: str) -> str:
    """Table / schema names cannot be bound as SQL parameters, so validate them strictly."""
    if not _IDENT.match(value or ""):
        raise ValueError(f"{name}={value!r} is not a valid identifier (letters, digits, underscore).")
    return value


# This application only reads real Databricks sources.
MODE = os.getenv("GEOMAP_MODE", "databricks").strip().lower()
if MODE != "databricks":
    raise ValueError("Only GEOMAP_MODE=databricks is supported. Configure the live Databricks connection.")

CATALOG = _ident("GEOMAP_CATALOG", os.getenv("GEOMAP_CATALOG", "bonitas_geo"))
SCHEMA = _ident("GEOMAP_SCHEMA", os.getenv("GEOMAP_SCHEMA", "geomap"))

# Tables produced by scripts 01 and 02 (landed in Delta under the same names).
TABLES = {
    "provider_master": "ProviderMaster",
    "product_network_provider": "ProductNetworkProvider",
    "practice_geocode": "PracticeGeocode",
    "provider_category": "ProviderCategory",
    "access_standard": "AccessStandard",
    "member_access": "MemberAccess",
    "specialist_alignment": "SpecialistHospitalAlignment",
    # Supporting tables for the app:
    "place_centroid": os.getenv("GEOMAP_PLACE_TABLE", "PlaceCentroid"),   # suburb / postcode centroids
    "option_name": os.getenv("GEOMAP_OPTION_TABLE", "ProductOption"),     # ProdCode -> OptionName
}
for _k, _v in TABLES.items():
    if _v:
        _ident(_k, _v)


def fq(key: str) -> str:
    """Fully qualified Unity Catalog table name."""
    return f"`{CATALOG}`.`{SCHEMA}`.`{TABLES[key]}`"


WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "")
HTTP_PATH = os.getenv("DATABRICKS_HTTP_PATH", "")
DBT_PROFILE = os.getenv("GEOMAP_DBT_PROFILE", "")
DBT_TARGET = os.getenv("GEOMAP_DBT_TARGET", "")
CACHE_TTL_SECONDS = int(os.getenv("GEOMAP_CACHE_TTL", "30"))
DATA_BACKEND = os.getenv('GEOMAP_BACKEND', 'live').strip().lower()
if DATA_BACKEND not in {'live', 'snapshot'}:
    raise ValueError('GEOMAP_BACKEND must be live or snapshot.')

MEMBER_CATALOG = _ident("GEOMAP_MEMBER_CATALOG", os.getenv("GEOMAP_MEMBER_CATALOG", "hive_metastore"))
MEMBER_SCHEMA = _ident("GEOMAP_MEMBER_SCHEMA", os.getenv("GEOMAP_MEMBER_SCHEMA", "care_coordination_reporting"))
MEMBER_TABLE = _ident("GEOMAP_CURRENT_MEMBER_TABLE", os.getenv("GEOMAP_CURRENT_MEMBER_TABLE", "vw_member_current"))
MEMBER_SOURCE = f"`{MEMBER_CATALOG}`.`{MEMBER_SCHEMA}`.`{MEMBER_TABLE}`"
MEMBERSHIP_SCHEMA = _ident("GEOMAP_MEMBERSHIP_SCHEMA", os.getenv("GEOMAP_MEMBERSHIP_SCHEMA", "membership_live"))

def membership_table(name):
    return f"`{MEMBER_CATALOG}`.`{MEMBERSHIP_SCHEMA}`.`{_ident('membership table', name)}`"

# Thresholds used by the alignment view (match Script 02).
ONSITE_KM = 0.5
NEAR_KM = 5.0
