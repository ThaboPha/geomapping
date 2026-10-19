"""Conservative public address estimates, never verified street geocodes."""
import re
from .geo import haversine_km


def select_address_estimate(provider, matches):
    if matches.empty:
        return None
    address = str(provider.get('DisplayAddress') or '').lower()
    locality = ' '.join(str(provider.get(key) or '') for key in ['Town', 'Suburb', 'ProvinceDescr']).lower()
    excluded = set(re.findall(r'[a-z]+', locality)) | {'south', 'africa', 'suite', 'room', 'floor', 'private', 'hospital'}
    tokens = set(re.findall(r'[a-z]{3,}', address)) - excluded
    if len(tokens) < 2:
        return None
    scored = matches.copy()
    scored['score'] = scored.Label.str.lower().map(lambda label: len(tokens & set(re.findall(r'[a-z]{3,}', label))))
    scored = scored[scored.score >= 2].sort_values('score', ascending=False)
    if scored.empty:
        return None
    best = scored.iloc[0]
    tied = scored[scored.score == best.score]
    if len(tied) > 1 and (haversine_km(best.Latitude, best.Longitude, tied.Latitude, tied.Longitude) > .2).any():
        return None
    return dict(SourceAddress=provider['DisplayAddress'], Latitude=float(best.Latitude),
                Longitude=float(best.Longitude), MapAddress=best.Label,
                MatchLevel='Public address estimate; unverified precision')


def estimate_public_address(provider):
    from .place_search import search_provider_address
    match = select_address_estimate(provider, search_provider_address(provider))
    if match:
        return match
    # Suite/building strings often hide the actual street query. Keep source
    # address for validation and provenance; request its street/locality suffix.
    chunks = [chunk.strip() for chunk in str(provider.get('DisplayAddress') or '').split(',') if chunk.strip()]
    if len(chunks) > 3:
        reduced = {**provider, 'DisplayAddress': ', '.join(chunks[-3:])}
        return select_address_estimate(provider, search_provider_address(reduced))
    return None
