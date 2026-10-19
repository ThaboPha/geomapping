-- Accepted address matches supplement the source; original provider records are unchanged.
-- Exact source-address matching prevents reuse after a practice changes address.
CREATE OR REPLACE VIEW hive_metastore.geomap.PracticeGeocode AS
SELECT p.PracNum,
 SHA2(COALESCE(p.GeocodeAddress,''),256) AS AddressHash,p.GeocodeAddress,
 CASE WHEN a.PracNum IS NOT NULL THEN CAST(a.Latitude AS DECIMAL(9,6))
      WHEN p.SourceLatitude BETWEEN -35 AND -22 AND p.SourceLongitude BETWEEN 16 AND 33.5
      THEN CAST(p.SourceLatitude AS DECIMAL(9,6)) ELSE CAST(NULL AS DECIMAL(9,6)) END AS Latitude,
 CASE WHEN a.PracNum IS NOT NULL THEN CAST(a.Longitude AS DECIMAL(9,6))
      WHEN p.SourceLatitude BETWEEN -35 AND -22 AND p.SourceLongitude BETWEEN 16 AND 33.5
      THEN CAST(p.SourceLongitude AS DECIMAL(9,6)) ELSE CAST(NULL AS DECIMAL(9,6)) END AS Longitude,
 CASE WHEN a.PracNum IS NOT NULL THEN a.MatchLevel
      WHEN p.SourceLatitude BETWEEN -35 AND -22 AND p.SourceLongitude BETWEEN 16 AND 33.5 THEN 'Suburb'
      ELSE 'Failed' END AS MatchLevel,
 CASE WHEN a.PracNum IS NOT NULL THEN a.Source ELSE 'providers_live.pracaddr_bronze' END AS GeocodeSource,
 CASE WHEN a.PracNum IS NOT NULL THEN a.GeocodedAt ELSE p.SourceIngestionTimestamp END AS GeocodeDate,
 CASE WHEN a.PracNum IS NOT NULL AND a.MatchLevel='Street' THEN 'VERIFIED_STREET_COORDINATE'
      WHEN a.PracNum IS NOT NULL THEN 'HIGH_CONFIDENCE_ADDRESS_GEOCODE_PREMISES_UNVERIFIED'
      WHEN p.SourceLatitude BETWEEN -35 AND -22 AND p.SourceLongitude BETWEEN 16 AND 33.5
        THEN 'UNVERIFIED_SOURCE_COORDINATE_CONSERVATIVELY_CLASSIFIED_AS_SUBURB'
      WHEN p.SourceLatitude IS NULL OR p.SourceLongitude IS NULL THEN 'MISSING_COORDINATE'
      ELSE 'OUTSIDE_PLAUSIBLE_SOUTH_AFRICA_BOUNDS' END AS CoordinateQualityStatus
FROM hive_metastore.geomap.ProviderMaster p
LEFT JOIN hive_metastore.geomap.ProviderAddressGeocode a
 ON a.PracNum=p.PracNum AND a.SourceAddress=p.DisplayAddress
 AND a.Latitude BETWEEN -35 AND -22 AND a.Longitude BETWEEN 16 AND 33.5
 AND (a.MatchLevel='Street' OR (a.Source LIKE 'Azure Maps Geocoding%'
      AND a.MatchLevel LIKE 'Azure Maps address (%'));
