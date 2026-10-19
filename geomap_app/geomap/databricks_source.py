"""Reads the GeoMap Delta tables in Unity Catalog through a Databricks SQL warehouse.

Auth: inside Databricks Apps the app's service principal is picked up automatically by
databricks.sdk Config(). Locally, set DATABRICKS_HOST and DATABRICKS_TOKEN (or a CLI profile).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
import os
from pathlib import Path
from urllib.parse import urlparse
from decimal import Decimal
from threading import RLock
import logging
from databricks import sql
from databricks.sql.exc import RequestError
from databricks.sdk.core import Config

from . import config
from .config import fq
from .data import DataSource, SPECIALIST_CATEGORIES
from .geo import bbox, haversine_sql

_QUERY_LOCK = RLock()


@st.cache_resource(show_spinner=False)
def _connection():
    if config.DBT_PROFILE:
        import yaml
        profile_path = Path(os.getenv("DBT_PROFILES_DIR", str(Path.home() / ".dbt"))) / "profiles.yml"
        profiles = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        profile = profiles[config.DBT_PROFILE]
        target = config.DBT_TARGET or profile["target"]
        settings = profile["outputs"][target]
        if settings.get("type") != "databricks":
            raise RuntimeError("The selected dbt profile must use the Databricks adapter.")
        token = settings.get("token", "")
        if token.startswith("{{"):
            raise RuntimeError("For a templated dbt token, use Databricks SDK authentication instead.")
        return sql.connect(
            server_hostname=settings["host"].removeprefix("https://").rstrip("/"),
            http_path=settings["http_path"], access_token=token,
            _socket_timeout=20, _retry_stop_after_attempts_duration=40,
            _retry_stop_after_attempts_count=2,
            enable_telemetry=False,
        )
    http_path = config.HTTP_PATH or (f"/sql/1.0/warehouses/{config.WAREHOUSE_ID}" if config.WAREHOUSE_ID else "")
    if not http_path:
        raise RuntimeError("Set DATABRICKS_HTTP_PATH, DATABRICKS_WAREHOUSE_ID, or GEOMAP_DBT_PROFILE.")
    cfg = Config()
    return sql.connect(
        server_hostname=urlparse(cfg.host if "://" in cfg.host else f"https://{cfg.host}").hostname,
        http_path=http_path,
        credentials_provider=lambda: cfg.authenticate,
        _socket_timeout=20, _retry_stop_after_attempts_duration=40,
        _retry_stop_after_attempts_count=2,
        enable_telemetry=False,
    )


def _query(statement: str, params: dict | None = None) -> pd.DataFrame:
    if not _QUERY_LOCK.acquire(timeout=45):
        raise RuntimeError('The live data connection is busy. Please try again shortly.')
    try:
        with _connection().cursor() as cur:
            cur.execute(statement, params or {})
            rows = cur.fetchall()
            cols = [c[0] for c in cur.description]
    except RequestError:
        # A transport failure may leave the pooled SQL session unusable.
        # The next user attempt must establish a fresh live connection.
        _connection.clear()
        logging.getLogger(__name__).warning('Live SQL transport failed; connection cache cleared.')
        raise
    except Exception as exc:
        logging.getLogger(__name__).warning('Live SQL request failed (%s).', type(exc).__name__)
        raise
    finally:
        _QUERY_LOCK.release()
    frame = pd.DataFrame([tuple(r) for r in rows], columns=cols)
    for column in frame:
        non_null = frame[column].dropna()
        if column in {"PracNum", "HospPracNum", "Latitude", "Longitude", "DistanceKm"} or (
            not non_null.empty and isinstance(non_null.iloc[0], Decimal)
        ):
            frame[column] = pd.to_numeric(frame[column])
    return frame


@st.cache_data(ttl=config.CACHE_TTL_SECONDS, show_spinner=False)
def _cached(statement: str, params: tuple = ()) -> pd.DataFrame:
    return _query(statement, dict(params))


def _in_list(values) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


class DatabricksSource(DataSource):
    mode = "databricks"

    def __init__(self):
        _query("SELECT 1 AS Connected")

    # --- reference ------------------------------------------------------------------
    def options(self):
        base = f"SELECT DISTINCT trim(ProdCode) AS ProdCode FROM {fq('product_network_provider')}"
        try:
            return _cached(
                f"SELECT p.ProdCode, coalesce(o.OptionName, p.ProdCode) AS OptionName "
                f"FROM ({base}) p LEFT JOIN {fq('option_name')} o ON trim(o.ProdCode) = p.ProdCode "
                f"ORDER BY OptionName")
        except Exception:  # option-name table not created yet
            df = _cached(base + " ORDER BY ProdCode")
            return df.assign(OptionName=df.ProdCode)

    def disciplines(self):
        return _cached(f"SELECT PracType, PracTypeDescr, ProviderCategory FROM {fq('provider_category')} "
                       f"WHERE PracType IS NOT NULL ORDER BY ProviderCategory, PracTypeDescr, PracType")

    def standards(self):
        return _cached(f"SELECT * FROM {fq('access_standard')}")

    # --- lookup ---------------------------------------------------------------------
    def search_places(self, text):
        t = (text or "").strip().lower()
        return _cached(
            f"SELECT Place, Town, PostCode, Province, Geotype, Latitude, Longitude FROM {fq('place_centroid')} "
            f"WHERE lower(Place) LIKE :q OR lower(Town) LIKE :q OR PostCode = :pc "
            f"ORDER BY Place LIMIT 25", (("q", f"%{t}%"), ("pc", t)))

    @property
    def member_lookup_enabled(self):
        return True

    def find_members(self, member_number):
        # Current active beneficiaries only; never put membership records in shared caches.
        return _query(
            f"SELECT DISTINCT memnum AS MemberNumber, benfcnum AS BeneficiaryNumber, "
            f"trim(product_code) AS ProdCode, scheme_code AS SchemeCode, "
            f"beneficiary_role AS BeneficiaryRole FROM {config.MEMBER_SOURCE} "
            "WHERE TRY_CAST(memnum AS BIGINT) = :m AND beneficiary_status = 'A' "
            "AND product_code IS NOT NULL AND trim(product_code) <> '' "
            "ORDER BY BeneficiaryNumber, ProdCode", {"m": int(member_number)})

    def find_member(self, member_number):
        df = self.find_members(member_number)
        return None if df.empty else df.iloc[0].to_dict()

    def registered_address(self, member_number, beneficiary_number):
        # Prefer the selected beneficiary's current address, residential/street
        # before postal; fall back to the account only if they have no address.
        frame = _query(f"""
            WITH addresses AS (
                SELECT trim(AddrType) AS AddressType, trim(Line1) AS Line1,
                    trim(Line2) AS Line2, trim(Line3) AS Line3, trim(Town) AS Town,
                    trim(PostCode) AS PostCode, trim(CntryCode) AS CountryCode,
                    EffDate, TimeStamp, 0 AS Priority, 'Beneficiary address' AS AddressSource
                FROM {config.membership_table('benfcaddr_bronze')}
                WHERE MemNum = :m AND BenfcNum = :b AND EffDate <= CURRENT_TIMESTAMP()
                UNION ALL
                SELECT trim(AddrType), trim(Line1), trim(Line2), trim(Line3), trim(Town),
                    trim(PostCode), trim(CntryCode), EffDate, TimeStamp, 1, 'Membership account address'
                FROM {config.membership_table('memaddr_bronze')}
                WHERE MemNum = :m AND EffDate <= CURRENT_TIMESTAMP()
            ), current_addresses AS (
                SELECT * FROM addresses
                QUALIFY row_number() OVER (PARTITION BY Priority, AddressType ORDER BY EffDate DESC, TimeStamp DESC) = 1
            )
            SELECT AddressType, Line1, Line2, Line3, Town, PostCode, CountryCode, AddressSource
            FROM current_addresses WHERE upper(AddressType) IN ('R', 'S', 'P')
                AND concat_ws('', Line1, Line2, Line3, Town, PostCode) <> ''
            ORDER BY Priority, CASE WHEN upper(AddressType) IN ('R', 'S') THEN 0 ELSE 1 END
            LIMIT 1""", {'m': int(member_number), 'b': int(beneficiary_number)})
        return None if frame.empty else frame.iloc[0].to_dict()

    def network_directory(self, prod_code=None):
        return _cached(f"""
            WITH networks AS (
                SELECT PracNum, concat_ws('; ', array_sort(collect_set(NetworkName))) AS Networks,
                    max(CAST(AssBlockActive AS INT)) AS AssBlockActive
                FROM {fq('product_network_provider')}
                WHERE (:prod IS NULL OR trim(ProdCode) = :prod) GROUP BY PracNum
            )
            SELECT pm.*, n.Networks, n.AssBlockActive,
                CASE WHEN n.AssBlockActive IS NULL THEN 'Unverified assignment status'
                     WHEN n.AssBlockActive <> 0 THEN 'Assignment blocked; check with scheme'
                     ELSE 'Assignment not blocked' END AS EligibilityStatus,
                CASE WHEN g.Latitude BETWEEN -35 AND -22 AND g.Longitude BETWEEN 16 AND 33.5
                     THEN CAST(g.Latitude AS DOUBLE) END AS Latitude,
                CASE WHEN g.Latitude BETWEEN -35 AND -22 AND g.Longitude BETWEEN 16 AND 33.5
                     THEN CAST(g.Longitude AS DOUBLE) END AS Longitude,
                coalesce(g.MatchLevel, 'Not geocoded') AS MatchLevel
            FROM {fq('provider_master')} pm JOIN networks n ON n.PracNum = pm.PracNum
            LEFT JOIN {fq('practice_geocode')} g ON g.PracNum = pm.PracNum
            ORDER BY pm.ProvinceDescr, pm.PracName""", (('prod', prod_code),))

    def membership_summary(self):
        return _cached(f"SELECT trim(product_code) AS ProdCode, count(*) AS Beneficiaries, "
                       "count(DISTINCT memnum) AS Memberships, "
                       "count_if(postal_code IS NOT NULL OR town IS NOT NULL) AS RegisteredAreas "
                       f"FROM {config.MEMBER_SOURCE} GROUP BY trim(product_code) ORDER BY ProdCode")

    def member_distribution(self):
        """Aggregate current membership_live beneficiaries; never return member IDs."""
        return _cached(f"""
            WITH profiles AS (
                SELECT MemNum, BenfcNum, BenfcStat, BenfcEndDate
                FROM {config.membership_table('benfcprof_bronze')}
                WHERE EffDate <= CURRENT_TIMESTAMP()
                QUALIFY row_number() OVER (PARTITION BY MemNum, BenfcNum
                    ORDER BY EffDate DESC, BenfcProfAsAt DESC, _ingestion_timestamp DESC) = 1
            ), subscriptions AS (
                SELECT MemNum, trim(ProdCode) AS ProdCode, Active
                FROM {config.membership_table('v_memsubsctrl')}
                WHERE EffDate <= CURRENT_TIMESTAMP()
                    AND (EffTo IS NULL OR EffTo >= CURRENT_TIMESTAMP())
                QUALIFY row_number() OVER (PARTITION BY MemNum
                    ORDER BY EffDate DESC, SubsCtrlAsAt DESC) = 1
            ), addresses AS (
                SELECT MemNum, BenfcNum, trim(Town) AS Town, trim(PostCode) AS PostCode,
                    upper(trim(AddrType)) AS AddrType
                FROM {config.membership_table('benfcaddr_bronze')}
                WHERE EffDate <= CURRENT_TIMESTAMP() AND upper(trim(AddrType)) IN ('R', 'S', 'P')
                QUALIFY row_number() OVER (PARTITION BY MemNum, BenfcNum
                    ORDER BY CASE WHEN upper(trim(AddrType)) IN ('R','S') THEN 0 ELSE 1 END,
                        EffDate DESC, _ingestion_timestamp DESC, TimeStamp DESC) = 1
            ), accounts AS (
                SELECT MemNum, trim(Town) AS Town, trim(PostCode) AS PostCode,
                    upper(trim(AddrType)) AS AddrType
                FROM {config.membership_table('memaddr_bronze')}
                WHERE EffDate <= CURRENT_TIMESTAMP() AND upper(trim(AddrType)) IN ('R', 'S', 'P')
                QUALIFY row_number() OVER (PARTITION BY MemNum
                    ORDER BY CASE WHEN upper(trim(AddrType)) IN ('R','S') THEN 0 ELSE 1 END,
                        EffDate DESC, _ingestion_timestamp DESC, TimeStamp DESC) = 1
            ), localities AS (
                SELECT s.ProdCode, coalesce(nullif(a.Town,''), nullif(m.Town,''), 'Unknown') AS Locality,
                    coalesce(nullif(a.PostCode,''), nullif(m.PostCode,'')) AS PostCode,
                    coalesce(a.AddrType, m.AddrType, 'Unknown') AS AddressType, count(*) AS Members
                FROM profiles p JOIN subscriptions s ON s.MemNum = p.MemNum
                LEFT JOIN addresses a ON a.MemNum = p.MemNum AND a.BenfcNum = p.BenfcNum
                LEFT JOIN accounts m ON m.MemNum = p.MemNum AND a.MemNum IS NULL
                WHERE upper(trim(p.BenfcStat)) = 'A'
                    AND (p.BenfcEndDate IS NULL OR p.BenfcEndDate >= CURRENT_TIMESTAMP())
                    AND coalesce(s.Active, true) AND s.ProdCode IS NOT NULL
                GROUP BY ALL
            ), places AS (
                SELECT lower(trim(Place)) AS Locality, trim(PostCode) AS PostCode,
                    CASE WHEN count(DISTINCT Province) = 1 THEN max(Province) END AS Province
                FROM {fq('place_centroid')} GROUP BY ALL
            )
            SELECT l.ProdCode, coalesce(p.Province, 'Unknown') AS Province,
                l.Locality, l.PostCode, l.AddressType, l.Members
            FROM localities l LEFT JOIN places p ON lower(l.Locality) = p.Locality
                AND l.PostCode = p.PostCode
            ORDER BY l.ProdCode, Province, l.Locality""")

    def quality_details(self, prod_code=None):
        return _cached(f"""
            SELECT pm.PracNumDisplay, pm.PracName, pm.ProviderCategory, pm.PracTypeDescr,
                pm.DisplayAddress, pm.ProvinceDescr, pm.IsNetworkProvider, pm.AddrQualityFlag,
                coalesce(g.MatchLevel, 'Not geocoded') AS MatchLevel,
                CASE WHEN g.Latitude BETWEEN -35 AND -22 AND g.Longitude BETWEEN 16 AND 33.5
                    THEN true ELSE false END AS HasCoordinates,
                g.GeocodeDate
            FROM {fq('provider_master')} pm LEFT JOIN {fq('practice_geocode')} g ON g.PracNum = pm.PracNum
            WHERE (:prod IS NULL OR EXISTS (SELECT 1 FROM {fq('product_network_provider')} n
                WHERE n.PracNum = pm.PracNum AND trim(n.ProdCode) = :prod))
            ORDER BY pm.IsNetworkProvider DESC, pm.PracName""", (('prod', prod_code),))

    def provider_location_quality(self):
        return _cached(f"""SELECT PracNumDisplay,PracName,ProviderCategory,PracTypeDescr,
            DisplayAddress,ProvinceDescr,IsNetworkProvider,AddrQualityFlag,MatchLevel,
            coalesce(Latitude BETWEEN -35 AND -22 AND Longitude BETWEEN 16 AND 33.5,false) AS HasCoordinates
            FROM `{config.CATALOG}`.`{config.SCHEMA}`.`ProviderLocation`
            ORDER BY IsNetworkProvider DESC,PracName""")

    def provider_location_freshness(self):
        return _cached(f"""SELECT count(*) AS Practices,
            count_if(Latitude BETWEEN -35 AND -22 AND Longitude BETWEEN 16 AND 33.5) AS Geocoded,
            (SELECT max(GeocodedAt) FROM `{config.CATALOG}`.`{config.SCHEMA}`.`ProviderAddressGeocode`) AS LastGeocode
            FROM `{config.CATALOG}`.`{config.SCHEMA}`.`ProviderLocation`""").iloc[0].to_dict()

    def providers_near(self, prod_code, lat, lon, category, prac_type, max_km, limit, include_unverified=False,
                       use_place_centroids=False, all_providers=False):
        lat_min, lat_max, lon_min, lon_max = bbox(lat, lon, max_km)
        params = {"prod": prod_code.strip(), "cat": category, "lat": float(lat), "lon": float(lon),
                  "lat_min": lat_min, "lat_max": lat_max, "lon_min": lon_min, "lon_max": lon_max,
                  "max_km": float(max_km), "include_unverified": bool(include_unverified),
                  "all_providers": bool(all_providers)}
        pt_clause = ""
        if prac_type is not None:
            pt_clause = "AND pm.PracType = :pt"
            params["pt"] = int(prac_type)
        coordinate_source = f"""SELECT PracNum, Latitude, Longitude, MatchLevel FROM {fq('practice_geocode')}"""
        if use_place_centroids:
            coordinate_source = f"""
                SELECT pm.PracNum, coalesce(g.Latitude, pc.Latitude) AS Latitude,
                    coalesce(g.Longitude, pc.Longitude) AS Longitude,
                    CASE WHEN g.Latitude IS NOT NULL AND g.Longitude IS NOT NULL THEN g.MatchLevel
                         WHEN pc.Latitude IS NOT NULL THEN 'Provisional place centroid'
                         ELSE 'Not geocoded' END AS MatchLevel
                FROM {fq('provider_master')} pm
                LEFT JOIN {fq('practice_geocode')} g ON g.PracNum = pm.PracNum
                LEFT JOIN (
                    SELECT lower(trim(Place)) AS Place, PostCode, Province,
                        avg(CAST(Latitude AS DOUBLE)) AS Latitude, avg(CAST(Longitude AS DOUBLE)) AS Longitude
                    FROM {fq('place_centroid')} GROUP BY lower(trim(Place)), PostCode, Province
                ) pc ON pc.Place = lower(trim(coalesce(nullif(trim(pm.Suburb), ''), pm.Town)))
                    AND pc.PostCode <=> pm.PostCode AND pc.Province <=> pm.ProvinceDescr
            """
        statement = f"""
            WITH coordinates AS ({coordinate_source}), e AS (
                SELECT PracNum,
                       concat_ws('; ', array_sort(collect_set(trim(NetworkName)))) AS Networks,
                       max(CAST(PrimaryNetworkInd AS INT)) AS PrimaryNetworkInd,
                       max(CAST(AssBlockActive AS INT))    AS AssBlockActive
                FROM {fq('product_network_provider')}
                WHERE trim(ProdCode) = :prod
                GROUP BY PracNum
            ), c AS (
                SELECT pm.PracNumDisplay, pm.PracName, pm.PracTypeDescr, pm.DisplayAddress, pm.PracticeEmail,
                       e.Networks, e.PrimaryNetworkInd, g.MatchLevel,
                       CASE WHEN e.PracNum IS NULL THEN 'Cover not confirmed for selected option'
                            WHEN e.AssBlockActive IS NULL THEN 'Unverified assignment status'
                            WHEN e.AssBlockActive <> 0 THEN 'Assignment blocked; check with scheme'
                            ELSE 'Assignment not blocked' END AS EligibilityStatus,
                       CAST(g.Latitude AS DOUBLE) AS Latitude, CAST(g.Longitude AS DOUBLE) AS Longitude,
                       {haversine_sql('g.Latitude', 'g.Longitude')} AS DistanceKm
                FROM {fq('provider_master')} pm
                LEFT JOIN e ON pm.PracNum = e.PracNum
                JOIN coordinates g ON g.PracNum = pm.PracNum
                WHERE (:all_providers OR (e.PracNum IS NOT NULL AND
                    (e.AssBlockActive = 0 OR (:include_unverified AND e.AssBlockActive IS NULL))))
                  AND pm.ProviderCategory = :cat {pt_clause}
                  AND g.Latitude  BETWEEN :lat_min AND :lat_max
                  AND g.Longitude BETWEEN :lon_min AND :lon_max
            )
            SELECT * FROM c WHERE DistanceKm <= :max_km ORDER BY DistanceKm, PracNumDisplay LIMIT {int(limit)}"""
        return _cached(statement, tuple(sorted(params.items())))

    def refresh(self):
        _cached.clear()

    def directory_provinces(self):
        return _cached(f"SELECT DISTINCT ProvinceDescr FROM {fq('provider_master')} "
                       "WHERE IsNetworkProvider = 1 AND ProvinceDescr IS NOT NULL ORDER BY ProvinceDescr")

    def location_area(self, lat, lon):
        params = (("lat", float(lat)), ("lon", float(lon)))
        return _cached(f"SELECT Place, Province, {haversine_sql('Latitude', 'Longitude')} AS DistanceKm "
                       f"FROM {fq('place_centroid')} WHERE Latitude IS NOT NULL AND Longitude IS NOT NULL "
                       "ORDER BY DistanceKm LIMIT 1", params)

    def unmapped_providers(self, prod_code, category, prac_type, limit, include_unverified=False, province=None,
                          all_providers=False):
        params = {"prod": prod_code, "cat": category, "include_unverified": bool(include_unverified),
                  "all_providers": bool(all_providers)}
        pt_clause = ""
        province_clause = ""
        if province:
            province_clause = "AND pm.ProvinceDescr = :province"
            params["province"] = province
        if prac_type is not None:
            pt_clause = "AND pm.PracType = :pt"
            params["pt"] = int(prac_type)
        return _cached(f"""
            WITH e AS (
                SELECT PracNum, concat_ws('; ', array_sort(collect_set(NetworkName))) AS Networks,
                    max(CAST(AssBlockActive AS INT)) AS AssBlockActive
                FROM {fq('product_network_provider')} WHERE trim(ProdCode) = :prod GROUP BY PracNum
            )
            SELECT pm.PracNumDisplay, pm.PracName, pm.PracTypeDescr, pm.DisplayAddress, pm.ProvinceDescr,
                pm.Suburb, pm.Town, pm.PostCode,
                e.Networks, 'Missing provider coordinates' AS LocationStatus,
                CASE WHEN e.PracNum IS NULL THEN 'Cover not confirmed for selected option'
                     WHEN e.AssBlockActive IS NULL THEN 'Unverified assignment status'
                     WHEN e.AssBlockActive <> 0 THEN 'Assignment blocked; check with scheme'
                     ELSE 'Assignment not blocked' END AS EligibilityStatus
            FROM {fq('provider_master')} pm LEFT JOIN e ON pm.PracNum = e.PracNum
            LEFT JOIN {fq('practice_geocode')} g ON g.PracNum = pm.PracNum
            WHERE pm.ProviderCategory = :cat {pt_clause}
                {province_clause}
                AND (:all_providers OR (e.PracNum IS NOT NULL AND
                    (e.AssBlockActive = 0 OR (:include_unverified AND e.AssBlockActive IS NULL))))
                AND (g.Latitude IS NULL OR g.Longitude IS NULL)
            ORDER BY pm.ProvinceDescr, pm.PracName LIMIT {int(limit)}
        """, tuple(sorted(params.items())))

    # --- analysis -------------------------------------------------------------------
    def access_histogram(self, planning=False):
        table = f'`{config.CATALOG}`.`{config.SCHEMA}`.`MemberAccessPlanning`' if planning else fq('member_access')
        contract = _cached(f"DESCRIBE TABLE {table}")
        columns = set(contract.col_name)
        members = 'sum(MemberCount)' if 'MemberCount' in columns else 'count(*)'
        assessed = "WHERE AssessmentStatus IN ('ASSESSED', 'MAPPED_DIRECTORY_ESTIMATE')" if 'AssessmentStatus' in columns else ''
        return _cached(f"""
            SELECT trim(ProdCode) AS ProdCode, Geotype, Province, District, ProviderCategory, Discipline,
                   CASE WHEN NearestKm IS NULL THEN 999
                        ELSE least(CAST(ceil(NearestKm) AS INT), 201) END AS KmBin,
                   {members} AS Members
            FROM {table}
            {assessed}
            GROUP BY ALL""")

    def member_assessment_summary(self, planning=False):
        """Aggregate readiness alongside measured coverage; no private addresses."""
        table = f'`{config.CATALOG}`.`{config.SCHEMA}`.`MemberAccessPlanning`' if planning else fq('member_access')
        return _cached(f"""SELECT ProdCode, ProviderCategory, Discipline, Province, District,
            Geotype, AssessmentStatus, sum(MemberCount) AS Members
            FROM {table} GROUP BY ALL""")

    def alignment(self, prod_code=None):
        from .geo import haversine_km
        directory = self.network_directory(prod_code)
        memberships = None
        if not prod_code:
            links = _cached(f"SELECT DISTINCT PracNum, trim(ProdCode) AS ProdCode FROM {fq('product_network_provider')}")
            memberships = links.groupby('PracNum').ProdCode.agg(set).to_dict()
        specialists = directory[directory.ProviderCategory.isin(SPECIALIST_CATEGORIES)].copy()
        hospitals = directory[directory.ProviderCategory == 'Hospital'].dropna(subset=['Latitude', 'Longitude'])
        rows = []
        for _, specialist in specialists.iterrows():
            eligible = hospitals
            if memberships is not None:
                options = memberships.get(specialist.PracNum, set())
                eligible = hospitals[hospitals.PracNum.map(lambda number: bool(options & memberships.get(number, set())))]
            record = specialist.to_dict()
            record.update(SpecialistMatchLevel=specialist.MatchLevel, HospPracNum=None,
                          HospName=None, HospMatchLevel=None, DistanceKm=None, LocationAlignment='Not geocoded')
            if pd.notna(specialist.Latitude) and pd.notna(specialist.Longitude):
                record['LocationAlignment'] = 'No mapped network hospital on selected option'
                if not eligible.empty:
                    distances = haversine_km(specialist.Latitude, specialist.Longitude, eligible.Latitude, eligible.Longitude)
                    hospital = eligible.loc[distances.idxmin()]
                    distance = float(distances.min())
                    record.update(HospPracNum=hospital.PracNum, HospName=hospital.PracName,
                                  HospMatchLevel=hospital.MatchLevel, DistanceKm=distance,
                                  LocationAlignment=('On-site / adjacent' if distance <= config.ONSITE_KM and
                                      specialist.MatchLevel == hospital.MatchLevel == 'Street' else
                                      'Near (<= 5 km)' if distance <= config.NEAR_KM else 'Distant (> 5 km)'))
            rows.append(record)
        return pd.DataFrame(rows, columns=list(specialists.columns) + ['SpecialistMatchLevel', 'HospPracNum',
            'HospName', 'HospMatchLevel', 'DistanceKm', 'LocationAlignment'])

    def network_hospitals(self, prod_code=None):
        directory = self.network_directory(prod_code)
        return directory[directory.ProviderCategory == 'Hospital'].copy()

    def recruitment_targets(self, prod_code=None):
        # No on-site recruitment claim is possible without a verified hospital.
        # Avoid expanding the all-provider spatial join when its result must be empty.
        hospitals = self.network_hospitals(prod_code)
        if hospitals.empty or not hospitals.MatchLevel.eq('Street').any():
            return pd.DataFrame(columns=['PracNumDisplay', 'PracName', 'PracTypeDescr',
                'ProvinceDescr', 'NetworkHospital', 'DistanceKm'])
        dist = haversine_sql("s.lat", "s.lon", "h.lat", "h.lon")
        return _cached(f"""
            WITH s AS (
                SELECT pm.PracNumDisplay, pm.PracName, pm.PracTypeDescr, pm.ProvinceDescr,
                       CAST(g.Latitude AS DOUBLE) AS lat, CAST(g.Longitude AS DOUBLE) AS lon
                FROM {fq('provider_master')} pm JOIN {fq('practice_geocode')} g ON g.PracNum = pm.PracNum
                WHERE pm.IsNetworkProvider = 0 AND g.MatchLevel = 'Street'
                  AND pm.ProviderCategory IN ({_in_list(SPECIALIST_CATEGORIES)})
            ), h AS (
                SELECT pm.PracName, CAST(g.Latitude AS DOUBLE) AS lat, CAST(g.Longitude AS DOUBLE) AS lon
                FROM {fq('provider_master')} pm JOIN {fq('practice_geocode')} g ON g.PracNum = pm.PracNum
                WHERE pm.IsNetworkProvider = 1 AND pm.ProviderCategory = 'Hospital' AND g.MatchLevel = 'Street'
                    AND (:prod IS NULL OR EXISTS (SELECT 1 FROM {fq('product_network_provider')} n
                        WHERE n.PracNum = pm.PracNum AND trim(n.ProdCode) = :prod))
            ), pairs AS (
                SELECT s.PracNumDisplay, s.PracName, s.PracTypeDescr, s.ProvinceDescr,
                       h.PracName AS NetworkHospital, {dist} AS DistanceKm
                FROM s JOIN h ON abs(s.lat - h.lat) < 0.01 AND abs(s.lon - h.lon) < 0.01
            )
            SELECT PracNumDisplay, PracName, PracTypeDescr, ProvinceDescr, NetworkHospital,
                   round(DistanceKm, 2) AS DistanceKm
            FROM pairs WHERE DistanceKm <= {config.ONSITE_KM}
            ORDER BY NetworkHospital, PracTypeDescr""", (('prod', prod_code),))

    def address_quality(self):
        return _cached(f"""
            SELECT pm.ProviderCategory, pm.IsNetworkProvider, pm.AddrQualityFlag,
                   coalesce(g.MatchLevel, 'Not geocoded') AS MatchLevel, count(*) AS Practices
            FROM {fq('provider_master')} pm
            LEFT JOIN {fq('practice_geocode')} g ON g.PracNum = pm.PracNum
            GROUP BY ALL""")

    def freshness(self):
        df = _cached(f"""
            SELECT (SELECT max(GeocodeDate) FROM {fq('practice_geocode')}) AS LastGeocode,
                   (SELECT count(*) FROM {fq('practice_geocode')} g JOIN {fq('provider_master')} pm ON pm.PracNum = g.PracNum
                    WHERE g.Latitude BETWEEN -35 AND -22 AND g.Longitude BETWEEN 16 AND 33.5) AS Geocoded,
                   (SELECT count(*) FROM {fq('provider_master')}) AS Practices""")
        return df.iloc[0].to_dict()
