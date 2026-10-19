"""Azure Maps match assessment and local, official-boundary classification."""
import json
import math
from pathlib import Path


def assess(item):
    result = dict(Latitude=None, Longitude=None, Confidence=None, FeatureType=None,
                  MatchCodes=[], CalculationMethod=None, ResultStatus='NO_MATCH', Accepted=False)
    if item.get('error'):
        result['ResultStatus'] = 'SERVICE_ERROR'
        return result
    features = item.get('features') or []
    if not features:
        return result
    feature = features[0]
    props = feature.get('properties', {})
    result.update(Confidence=props.get('confidence'), FeatureType=props.get('type'),
                  MatchCodes=props.get('matchCodes') or [])
    points = props.get('geocodePoints') or []
    point = next((p for p in points if 'Display' in p.get('usageTypes', [])), points[0] if points else {})
    geometry = point.get('geometry') or feature.get('geometry') or {}
    coords = geometry.get('coordinates') or []
    result['CalculationMethod'] = point.get('calculationMethod')
    if len(coords) < 2 or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in coords[:2]):
        result['ResultStatus'] = 'INVALID_COORDINATES'
        return result
    lon, lat = coords[:2]
    result.update(Latitude=lat, Longitude=lon)
    country = props.get('address', {}).get('countryRegion', {}).get('ISO', '')
    if country != 'ZA' or not (-35 <= lat <= -22 and 16 <= lon <= 33.5):
        result['ResultStatus'] = 'OUTSIDE_SOUTH_AFRICA'
        return result
    if result['Confidence'] != 'High' or set(result['MatchCodes']) != {'Good'}:
        result['ResultStatus'] = 'REVIEW_MATCH_QUALITY'
        return result
    if result['FeatureType'] != 'Address':
        result['ResultStatus'] = 'APPROXIMATE_LOCATION'
        return result
    # Do not silently resolve two equally strong, geographically different candidates.
    for alternative in features[1:]:
        other = alternative.get('properties', {})
        xy = alternative.get('geometry', {}).get('coordinates') or []
        if other.get('confidence') == 'High' and other.get('type') == 'Address' and len(xy) >= 2:
            separation = math.hypot((xy[0]-lon)*111*math.cos(math.radians(lat)), (xy[1]-lat)*111)
            if separation > 0.1:
                result['ResultStatus'] = 'AMBIGUOUS_CANDIDATES'
                return result
    result.update(ResultStatus='ACCEPTED_ADDRESS', Accepted=True)
    return result


class BoundaryClassifier:
    def __init__(self, directory):
        import numpy as np
        import shapely
        from shapely.geometry import Polygon, shape
        from shapely.strtree import STRtree
        self.np = np
        self.shapely = shapely
        self.layers = {}
        self.metros = []
        segments = []
        for name in ('municipalities', 'provinces'):
            payload = json.loads((Path(directory) / (name + '.geojson')).read_text())
            features = payload['features']
            geometries = []
            for feature in features:
                geometry = feature['geometry']
                if geometry['type'] == 'EsriPolygon':
                    polygon = shapely.GeometryCollection()
                    for ring in geometry['rings']:
                        polygon = polygon.symmetric_difference(shapely.make_valid(Polygon(ring)))
                else:
                    polygon = shapely.make_valid(shape(geometry))
                geometries.append(polygon)
                if name == 'municipalities' and feature['properties'].get('Category') == 'A':
                    self.metros.append(polygon)
                    rings = geometry.get('rings', [])
                    if not rings:
                        rings = geometry['coordinates'] if geometry['type'] == 'Polygon' else [r for p in geometry['coordinates'] for r in p]
                    for ring in rings:
                        segments.extend((a[:2], b[:2]) for a, b in zip(ring, ring[1:]))
            self.layers[name] = (features, STRtree(geometries))
        self.metro_shape = shapely.union_all(self.metros)
        self.segments = np.asarray(segments, dtype=float)
        if not len(self.segments):
            raise ValueError('Official metro boundary segments are missing.')

    def classify(self, lat, lon):
        from geomap.geo import haversine_km
        from geomap.area_classification import distance_area
        point = self.shapely.Point(lon, lat)
        props = {}
        for name, (features, tree) in self.layers.items():
            hits = tree.query(point, predicate='within')
            props[name] = features[int(hits[0])]['properties'] if len(hits) == 1 else {}
        province = props['provinces'].get('ProvinceName', 'Unknown')
        province = {'Kwazulu-Natal': 'KwaZulu-Natal', 'Northern Province': 'Limpopo'}.get(province, province)
        district = props['municipalities'].get('DistrictName') or props['municipalities'].get('MapTitle') or 'Unknown'
        if self.metro_shape.covers(point):
            distance = 0.0
        else:
            np = self.np
            scaled = (self.segments - np.array([lon, lat])) * np.array([111.320*math.cos(math.radians(lat)), 110.574])
            start = scaled[:, 0]
            delta = scaled[:, 1] - start
            denominator = (delta*delta).sum(axis=1)
            ratio = np.clip(np.divide(-(start*delta).sum(axis=1), denominator,
                                     out=np.zeros_like(denominator), where=denominator != 0), 0, 1)
            nearest = start + ratio[:, None]*delta
            index = int(np.argmin((nearest*nearest).sum(axis=1)))
            original = self.segments[index, 0] + ratio[index]*(self.segments[index, 1]-self.segments[index, 0])
            distance = float(haversine_km(lat, lon, original[1], original[0]))
        return dict(Province=province, District=district, Geotype=distance_area(distance), MetroDistanceKm=distance)
