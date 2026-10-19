"""Distance helpers. Databricks has no SQL Server geography type, so distances use haversine."""
import math

import numpy as np

EARTH_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km. Accepts scalars or numpy arrays (broadcasts)."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def bbox(lat: float, lon: float, km: float):
    """Lat/lon box that contains a circle of radius km (cheap pre-filter before haversine)."""
    dlat = km / 110.574
    dlon = km / (111.320 * max(math.cos(math.radians(lat)), 0.01))
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon


def haversine_sql(lat_col: str, lon_col: str, lat_param: str = ":lat", lon_param: str = ":lon") -> str:
    """Databricks SQL expression for haversine distance in km."""
    return (
        f"2 * {EARTH_KM} * asin(sqrt("
        f"pow(sin(radians({lat_col} - {lat_param}) / 2), 2) + "
        f"cos(radians({lat_param})) * cos(radians({lat_col})) * "
        f"pow(sin(radians({lon_col} - {lon_param}) / 2), 2)))"
    )
