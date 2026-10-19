"""Point-in-polygon classification with no nearest-town or rural fallback."""

def in_ring(x,y,ring):
    inside=False
    for a,b in zip(ring,ring[1:]+ring[:1]):
        ax,ay=a[:2]; bx,by=b[:2]
        if (ay>y)!=(by>y) and x<(bx-ax)*(y-ay)/(by-ay)+ax:
            inside=not inside
    return inside


def contains(geometry,x,y):
    kind=geometry['type']
    if kind=='EsriPolygon':
        return sum(in_ring(x,y,ring) for ring in geometry['rings']) % 2 == 1
    polygons=[geometry['coordinates']] if kind=='Polygon' else geometry['coordinates'] if kind=='MultiPolygon' else []
    return any(in_ring(x,y,p[0]) and not any(in_ring(x,y,hole) for hole in p[1:]) for p in polygons)


def feature_at(features,x,y):
    hits=[]
    for feature in features:
        if '_bbox' not in feature:
            geometry=feature['geometry']
            def points(value):
                if value and isinstance(value[0],(int,float)):
                    yield value
                else:
                    for item in value:
                        yield from points(item)
            coords=list(points(geometry.get('rings',geometry.get('coordinates',[]))))
            feature['_bbox']=(min(p[0] for p in coords),min(p[1] for p in coords),max(p[0] for p in coords),max(p[1] for p in coords))
        left,bottom,right,top=feature['_bbox']
        if left<=x<=right and bottom<=y<=top and contains(feature['geometry'],x,y):
            hits.append(feature['properties'])
    return hits[0] if len(hits)==1 else None


def classify_point(lon,lat,municipalities,provinces,settlements=None):
    muni=feature_at(municipalities,lon,lat)
    province=feature_at(provinces,lon,lat)
    result=dict(Province=province.get('ProvinceName','Unknown') if province else 'Unknown',
        District='Unknown',Geotype='Unknown')
    if muni:
        result['District']=muni.get('DistrictName') or muni.get('MapTitle') or 'Unknown'
        if str(muni.get('Category','')).strip().upper()=='A':
            result['Geotype']='Metro'
    # Urban/rural can only come from an explicit settlement classification layer.
    # Non-metropolitan does not imply rural.
    if result['Geotype']=='Unknown' and settlements:
        settlement=feature_at(settlements,lon,lat)
        if settlement and settlement.get('Geotype') in {'Urban','Rural'}:
            result['Geotype']=settlement['Geotype']
    return result


def metro_distance_km(lon, lat, municipalities):
    """Shortest approximate ground distance to a metro boundary; zero inside."""
    import math
    from .geo import haversine_km
    metros=[f for f in municipalities if str(f['properties'].get('Category','')).strip().upper()=='A']
    if not metros:
        raise ValueError('Metro boundaries are required.')
    if feature_at(metros,lon,lat):
        return 0.0
    sx=111.320*math.cos(math.radians(lat)); sy=110.574
    best=float('inf'); nearest=None
    for feature in metros:
        geometry=feature['geometry']
        if geometry['type']=='EsriPolygon':
            rings=geometry['rings']
        elif geometry['type']=='Polygon':
            rings=geometry['coordinates']
        else:
            rings=[ring for polygon in geometry['coordinates'] for ring in polygon]
        for ring in rings:
            for a,b in zip(ring,ring[1:]):
                ax=(a[0]-lon)*sx; ay=(a[1]-lat)*sy
                bx=(b[0]-lon)*sx; by=(b[1]-lat)*sy
                dx=bx-ax; dy=by-ay
                denom=dx*dx+dy*dy
                t=max(0.0,min(1.0,-(ax*dx+ay*dy)/denom)) if denom else 0.0
                distance=(ax+t*dx)**2+(ay+t*dy)**2
                if distance<best:
                    best=distance
                    nearest=(a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1]))
    return float(haversine_km(lat,lon,nearest[1],nearest[0]))


def distance_area(distance_km):
    if distance_km < 0:
        raise ValueError('Distance cannot be negative.')
    return 'Metro' if distance_km < 10 else 'Urban' if distance_km < 40 else 'Rural'
