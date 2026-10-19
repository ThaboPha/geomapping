"""Data access layer for live Databricks GeoMap views."""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd
import streamlit as st

from . import config

CATEGORIES = ["GP", "Core Specialist", "Other Specialist", "Hospital", "Day Hospital"]
SPECIALIST_CATEGORIES = ["Core Specialist", "Other Specialist", "Hospital-based Specialist"]


class DataSource(ABC):
    mode: str = "base"

    # --- reference data -------------------------------------------------------------
    @abstractmethod
    def options(self) -> pd.DataFrame:
        """ProdCode, OptionName"""

    @abstractmethod
    def disciplines(self) -> pd.DataFrame:
        """PracType, PracTypeDescr, ProviderCategory"""

    @abstractmethod
    def standards(self) -> pd.DataFrame:
        """ProviderCategory, Geotype, RadiusKm, TargetCoveragePct"""

    # --- call centre lookup ---------------------------------------------------------
    @abstractmethod
    def search_places(self, text: str) -> pd.DataFrame:
        """Place, Town, PostCode, Province, Geotype, Latitude, Longitude"""

    @property
    def member_lookup_enabled(self) -> bool:
        return False

    def find_member(self, member_number: str) -> dict | None:
        """First current beneficiary record; use find_members for beneficiary selection."""
        return None

    def find_members(self, member_number: str) -> pd.DataFrame:
        """Current active MemberNumber, BeneficiaryNumber, ProdCode, SchemeCode, BeneficiaryRole."""
        raise NotImplementedError("A live current-membership source is required.")

    @abstractmethod
    def providers_near(self, prod_code: str, lat: float, lon: float, category: str,
                       prac_type: int | None, max_km: float, limit: int,
                       include_unverified: bool = False, use_place_centroids: bool = False,
                       all_providers: bool = False) -> pd.DataFrame:
        """PracNumDisplay, PracName, PracTypeDescr, DisplayAddress, PracticeEmail, Networks,
        PrimaryNetworkInd, MatchLevel, Latitude, Longitude, DistanceKm (sorted ascending)"""

    def unmapped_providers(self, prod_code: str, category: str, prac_type: int | None,
                          limit: int, include_unverified: bool = False, province: str | None = None,
                          all_providers: bool = False) -> pd.DataFrame:
        return pd.DataFrame()

    # --- analysis -------------------------------------------------------------------
    @abstractmethod
    def access_histogram(self) -> pd.DataFrame:
        """ProdCode, Geotype, Province, District, ProviderCategory, Discipline, KmBin, Members.
        KmBin = ceil(nearest km), capped at 201; 999 = no eligible provider."""

    @abstractmethod
    def alignment(self) -> pd.DataFrame:
        """SpecialistHospitalAlignment + specialist Latitude, Longitude"""

    @abstractmethod
    def network_hospitals(self) -> pd.DataFrame:
        """PracNum, PracName, ProvinceDescr, Latitude, Longitude"""

    @abstractmethod
    def recruitment_targets(self) -> pd.DataFrame:
        """PracNumDisplay, PracName, PracTypeDescr, ProvinceDescr, NetworkHospital, DistanceKm"""

    @abstractmethod
    def address_quality(self) -> pd.DataFrame:
        """ProviderCategory, IsNetworkProvider, AddrQualityFlag, MatchLevel, Practices"""

    @abstractmethod
    def freshness(self) -> dict:
        """LastGeocode, Geocoded, Practices"""

    # --- derived (shared) -----------------------------------------------------------
    def hospital_gaps(self, prod_code=None) -> pd.DataFrame:
        """Network hospitals x core disciplines with no contracted specialist on-site or nearby."""
        al = self.alignment(prod_code)
        hosp = self.network_hospitals(prod_code)
        if hosp.empty:
            return pd.DataFrame(columns=['Hospital', 'Province', 'Discipline', 'Nearby', 'Assessment'])
        disc = self.disciplines()
        core = disc.loc[disc.ProviderCategory.isin(["Core Specialist", "Hospital-based Specialist"]),
                        "PracTypeDescr"].drop_duplicates()
        near = (al[al.LocationAlignment.isin(["On-site / adjacent", "Near (<= 5 km)"])]
                .groupby(["HospPracNum", "PracTypeDescr"]).size().rename("Nearby").reset_index())
        grid = hosp[["PracNum", "PracName", "ProvinceDescr"]].merge(core.to_frame(), how="cross")
        grid = grid.merge(near, how="left", left_on=["PracNum", "PracTypeDescr"],
                          right_on=["HospPracNum", "PracTypeDescr"])
        grid["Nearby"] = grid["Nearby"].fillna(0).astype(int)
        unlocated = set(al.loc[al.Latitude.isna() | al.Longitude.isna(), 'PracTypeDescr'])
        missing_hospitals = set(hosp.loc[hosp.Latitude.isna() | hosp.Longitude.isna(), 'PracNum'])
        grid['Assessment'] = grid.apply(lambda row: 'Mapped specialist nearby' if row.Nearby > 0 else
            'Not assessed: missing coordinates' if row.PracNum in missing_hospitals or row.PracTypeDescr in unlocated
            else 'No mapped specialist nearby', axis=1)
        grid['Nearby'] = grid['Nearby'].astype('Int64')
        grid.loc[grid.Assessment == 'Not assessed: missing coordinates', 'Nearby'] = pd.NA
        return (grid.rename(columns={"PracName": "Hospital", "PracTypeDescr": "Discipline",
                                     "ProvinceDescr": "Province"})
                [["Hospital", "Province", "Discipline", "Nearby", "Assessment"]])


@st.cache_resource(show_spinner="Connecting to data…")
def get_source() -> DataSource:
    if config.DATA_BACKEND == 'snapshot':
        import os
        from pathlib import Path
        from .snapshot_source import SnapshotSource
        return SnapshotSource(os.getenv('GEOMAP_SNAPSHOT_DIR', str(Path(__file__).parents[1]/'snapshotdata')))
    from .databricks_source import DatabricksSource
    return DatabricksSource()
