"""Distance metrics use numeric, assessed pairs only."""
import pandas as pd


def distance_summary(frame):
    distances = pd.to_numeric(frame.DistanceKm, errors='coerce')
    valid = distances.notna() & distances.ge(0)
    assessed = int(valid.sum())
    within = int((valid & distances.le(5)).sum())
    above = int((valid & distances.gt(5)).sum())
    return dict(assessed=assessed, unknown=len(frame) - assessed, within=within, above=above,
                within_pct=100 * within / assessed if assessed else None,
                above_pct=100 * above / assessed if assessed else None)
