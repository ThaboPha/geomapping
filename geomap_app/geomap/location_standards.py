"""Location-based network standards, independent of member population records."""
import pandas as pd
from .geo import haversine_km


def assess_option(directory, loc, radius):
    frame = directory.drop_duplicates('PracNumDisplay').copy()
    frame['Latitude'] = pd.to_numeric(frame.Latitude, errors='coerce')
    frame['Longitude'] = pd.to_numeric(frame.Longitude, errors='coerce')
    valid = frame.Latitude.between(-35, -22) & frame.Longitude.between(16, 33.5)
    frame['DistanceKm'] = float('nan')
    frame.loc[valid, 'DistanceKm'] = haversine_km(loc['lat'], loc['lon'], frame.loc[valid, 'Latitude'], frame.loc[valid, 'Longitude'])
    frame['WithinStandard'] = valid & frame.DistanceKm.le(radius)
    nearest = frame.DistanceKm.min()
    nearby = int(frame.WithinStandard.sum())
    unknown = int((~valid).sum())
    if nearby:
        status = 'Provider within standard'
    elif frame.empty:
        status = 'No network providers listed'
    elif unknown:
        status = 'Unresolved: provider locations missing'
    else:
        status = 'Outside tested standard'
    return frame, dict(Providers=len(frame), Mapped=int(valid.sum()), Unmapped=unknown,
        Nearby=nearby, NearestKm=None if pd.isna(nearest) else float(nearest), Assessment=status)
