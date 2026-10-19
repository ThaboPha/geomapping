"""Validate geocoder results before loading them into the member pipeline."""
import math
import re

PROVINCES = {'Eastern Cape','Free State','Gauteng','KwaZulu-Natal','Limpopo',
    'Mpumalanga','North West','Northern Cape','Western Cape'}
LEVELS = {'Street','Suburb','Postcode','Provisional provider-derived area centroid'}


def validate_result(row):
    key=str(row.get('AddressKey') or '').strip().lower()
    if not re.fullmatch('[a-f0-9]{64}',key):
        raise ValueError('AddressKey must be a SHA-256 key from the member queue.')
    lat,lon=float(row['Latitude']),float(row['Longitude'])
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-35<=lat<=-22 and 16<=lon<=33.5):
        raise ValueError('Coordinates must be valid South African coordinates.')
    province=str(row.get('Province') or 'Unknown').strip()
    if province not in PROVINCES | {'Unknown'}:
        raise ValueError('Province must use a recognised South African province name.')
    geotype=str(row.get('Geotype') or 'Unknown').strip()
    if geotype not in {'Metro','Urban','Rural','Unknown'}:
        raise ValueError('Geotype must be Metro, Urban, Rural or Unknown.')
    district=str(row.get('District') or 'Unknown').strip()
    level=str(row.get('MatchLevel') or '').strip()
    if level not in LEVELS:
        raise ValueError('MatchLevel must describe street, suburb, postcode or provisional area accuracy.')
    source=str(row.get('Source') or '').strip()
    if not source:
        raise ValueError('Source is required for traceability.')
    confidence=row.get('Confidence')
    confidence=float(confidence) if confidence not in (None,'') else None
    if confidence is not None and (not math.isfinite(confidence) or not 0<=confidence<=1):
        raise ValueError('Confidence must be between zero and one.')
    return dict(AddressKey=key,Latitude=lat,Longitude=lon,Province=province,
        District=district,Geotype=geotype,MatchLevel=level,Confidence=confidence,
        Source=source,Status='MATCHED')
