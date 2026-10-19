"""Address preparation and acceptance rules for the authorised provider exercise."""
import hashlib
import json
import re
from member_azure_maps import assess

METHODS = {'Rooftop', 'Parcel', 'Interpolation', 'InterpolationOffset'}


def clean_address(row):
    if str(row.get('AddrType') or '').upper() != 'S':
        return None
    original = str(row.get('DisplayAddress') or '').strip()
    if not original or re.search(r'\b(?:P[ .]*O[ .]*BOX|PRIVATE BAG)\b', original, re.I):
        return None
    parts=[]
    for field in ('Line1','Line2','Line3','Suburb'):
        value=str(row.get(field) or '').strip()
        # Remove room/unit identifiers, retaining any street/building text after them.
        value=re.sub(r'\b(?:ROOM|SUITE|UNIT|FLOOR)\s*[A-Z]?\d+[A-Z]?\b[, ]*','',value,flags=re.I).strip(' ,')
        if value and value.casefold() not in [p.casefold() for p in parts]:
            parts.append(value)
    if not parts:
        return None
    request=dict(addressLine=', '.join(parts),locality=str(row.get('Town') or '').strip(),
                 postalCode=str(row.get('PostCode') or '').strip(),countryRegion='ZA',top=2)
    # Only merge identical cleaned requests, never just matching towns or postcodes.
    canonical={k:re.sub(r'\s+',' ',v).strip().upper() if isinstance(v,str) else v for k,v in request.items()}
    key=hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()
    return key,request


def assess_provider(item, request, classifier):
    result=assess(item)
    feature=(item.get('features') or [{}])[0]
    address=feature.get('properties',{}).get('address',{})
    result.update(MapAddress=address.get('formattedAddress'),Province='Unknown',District='Unknown',Geotype='Unknown',
                  ReturnedPostCode=address.get('postalCode'))
    if result['Accepted']:
        if result['CalculationMethod'] not in METHODS:
            result.update(Accepted=False,ResultStatus='REVIEW_POSITION_METHOD')
        else:
            result.update(classifier.classify(result['Latitude'],result['Longitude']))
            before=re.sub(r'\D','',request.get('postalCode',''))
            after=re.sub(r'\D','',address.get('postalCode') or '')
            if before and after and before.zfill(4)!=after.zfill(4):
                result.update(Accepted=False,ResultStatus='REVIEW_POSTCODE_CONFLICT')
            if result['Province']=='Unknown':
                result.update(Accepted=False,ResultStatus='REVIEW_BOUNDARY')
    return result


def coordinate_level(method):
    return f'Azure Maps address ({method}; premises unverified)'
