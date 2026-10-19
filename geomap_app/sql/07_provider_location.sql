-- Current provider positions for alignment; source tables remain unchanged.
CREATE OR REPLACE VIEW hive_metastore.geomap.ProviderLocation AS
WITH places AS (
 SELECT lower(trim(Place)) AS Place,trim(PostCode) AS PostCode,Province,
 max(CAST(Latitude AS DOUBLE)) AS Latitude,max(CAST(Longitude AS DOUBLE)) AS Longitude
 FROM hive_metastore.geomap.PlaceCentroid
 WHERE Latitude BETWEEN -35 AND -22 AND Longitude BETWEEN 16 AND 33.5
 GROUP BY lower(trim(Place)),trim(PostCode),Province
 HAVING count(DISTINCT struct(Latitude,Longitude))=1
), matched AS (
 SELECT p.PracNum,pc.Latitude,pc.Longitude
 FROM hive_metastore.geomap.ProviderMaster p JOIN places pc
 ON pc.Place=lower(trim(coalesce(nullif(trim(p.Suburb),''),p.Town)))
 AND pc.PostCode=trim(p.PostCode) AND pc.Province=p.ProvinceDescr
)
SELECT p.*,
 CASE WHEN g.Latitude BETWEEN -35 AND -22 AND g.Longitude BETWEEN 16 AND 33.5
 THEN CAST(g.Latitude AS DOUBLE) ELSE coalesce(a.Latitude,m.Latitude) END AS Latitude,
 CASE WHEN g.Latitude BETWEEN -35 AND -22 AND g.Longitude BETWEEN 16 AND 33.5
 THEN CAST(g.Longitude AS DOUBLE) ELSE coalesce(a.Longitude,m.Longitude) END AS Longitude,
 CASE WHEN g.Latitude BETWEEN -35 AND -22 AND g.Longitude BETWEEN 16 AND 33.5
 THEN coalesce(g.MatchLevel,'Unverified source coordinate')
 WHEN a.Latitude IS NOT NULL THEN a.MatchLevel
 WHEN m.Latitude IS NOT NULL THEN 'Provisional place centroid' ELSE 'Not geocoded' END AS MatchLevel
FROM hive_metastore.geomap.ProviderMaster p
LEFT JOIN hive_metastore.geomap.PracticeGeocode g ON g.PracNum=p.PracNum
LEFT JOIN matched m ON m.PracNum=p.PracNum
LEFT JOIN hive_metastore.geomap.ProviderAddressGeocode a ON a.PracNum=p.PracNum AND a.SourceAddress=p.DisplayAddress;

CREATE OR REPLACE VIEW hive_metastore.geomap.ProviderGeocodingQueue AS
SELECT PracNum,PracNumDisplay,PracName,ProviderCategory,DisplayAddress,ProvinceDescr,
 Latitude,Longitude,MatchLevel,
 CASE WHEN Latitude IS NULL OR Longitude IS NULL THEN 'GEOCODING_REQUIRED'
 ELSE 'STREET_VERIFICATION_REQUIRED' END AS GeocodeStatus
FROM hive_metastore.geomap.ProviderLocation
WHERE MatchLevel<>'Street';
