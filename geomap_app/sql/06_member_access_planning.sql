-- Product-linked mapped-directory planning estimates. These do not establish network membership or cover.
-- Missing provider coordinates can overstate distance gaps; measured availability is a lower bound.
CREATE OR REPLACE VIEW hive_metastore.geomap.MemberLocationPlanning AS
SELECT * EXCEPT(LocationStatus),
 CASE WHEN AddressType IN ('R','S') AND Latitude BETWEEN -35 AND -22
 AND Longitude BETWEEN 16 AND 33.5 AND Geotype IN ('Metro','Urban','Rural')
 AND Province<>'Unknown' AND District<>'Unknown' THEN 'READY' ELSE LocationStatus END AS LocationStatus
FROM hive_metastore.geomap.MemberLocation;

CREATE OR REPLACE VIEW hive_metastore.geomap.MemberAccessPlanning AS
WITH current_links AS (
 SELECT PracNum,upper(trim(ProdCode)) AS ProdCode,EffTo
 FROM hive_metastore.providers_live.pracpracgrpprod_bronze
 WHERE EffDate<=current_timestamp() AND nullif(trim(ProdCode),'') IS NOT NULL
 QUALIFY row_number() OVER (PARTITION BY PracNum,upper(trim(ProdCode)),upper(trim(PracGrpCode))
 ORDER BY EffDate DESC,PracPracGrpProdAsAt DESC,_ingestion_timestamp DESC)=1
), targets AS (
 SELECT 'GP' AS ProviderCategory, CAST(NULL AS INT) AS PracType, 'GP' AS Discipline
 UNION ALL SELECT 'Hospital', CAST(NULL AS INT), 'Network hospital'
 UNION ALL SELECT DISTINCT ProviderCategory, PracType, PracTypeDescr
 FROM hive_metastore.geomap.ProviderCategory
 WHERE ProviderCategory IN ('Core Specialist','Other Specialist')
), providers AS (
 SELECT DISTINCT trim(n.ProdCode) AS ProdCode, p.PracNum, p.ProviderCategory, p.PracType,
 coalesce(g.Latitude,pc.Latitude) AS Latitude, coalesce(g.Longitude,pc.Longitude) AS Longitude,
 coalesce(coalesce(g.Latitude,pc.Latitude) BETWEEN -35 AND -22 AND coalesce(g.Longitude,pc.Longitude) BETWEEN 16 AND 33.5,false) AS Located
 FROM current_links n
 JOIN hive_metastore.geomap.ProviderMaster p ON p.PracNum=n.PracNum
 LEFT JOIN hive_metastore.geomap.PracticeGeocode g ON g.PracNum=p.PracNum
 LEFT JOIN (
 SELECT lower(trim(Place)) AS Place,trim(PostCode) AS PostCode,Province,
 max(CAST(Latitude AS DOUBLE)) AS Latitude,max(CAST(Longitude AS DOUBLE)) AS Longitude
 FROM hive_metastore.geomap.PlaceCentroid
 GROUP BY lower(trim(Place)),trim(PostCode),Province
 HAVING count(DISTINCT struct(Latitude,Longitude))=1
 ) pc ON pc.Place=lower(trim(coalesce(nullif(trim(p.Suburb),''),p.Town)))
 AND pc.PostCode=trim(p.PostCode) AND pc.Province=p.ProvinceDescr
 WHERE n.EffTo IS NULL OR n.EffTo>=current_timestamp()
), provider_status AS (
 SELECT ProdCode,ProviderCategory,PracType,count(*) AS Providers,
 count_if(NOT Located) AS Unlocated FROM providers GROUP BY ALL
), target_status AS (
 SELECT codes.ProdCode,t.ProviderCategory,t.PracType,t.Discipline,
 coalesce(sum(p.Providers),0) AS ListedProviders,coalesce(sum(p.Unlocated),0) AS UnlocatedProviders
 FROM (SELECT DISTINCT ProdCode FROM hive_metastore.geomap.MemberLocationPlanning) codes
 CROSS JOIN targets t LEFT JOIN provider_status p ON p.ProdCode=codes.ProdCode
 AND p.ProviderCategory=t.ProviderCategory AND (t.PracType IS NULL OR t.PracType=p.PracType)
 GROUP BY ALL
), measured AS (
 SELECT m.Latitude,m.Longitude,m.ProdCode,t.ProviderCategory,t.Discipline,
 min(6371.0088*2*asin(sqrt(least(1.0,
 pow(sin(radians(p.Latitude-m.Latitude)/2),2)+cos(radians(m.Latitude))*cos(radians(p.Latitude))
 *pow(sin(radians(p.Longitude-m.Longitude)/2),2))))) AS NearestKm
 FROM (SELECT DISTINCT ProdCode,Latitude,Longitude FROM hive_metastore.geomap.MemberLocationPlanning WHERE LocationStatus='READY') m
 JOIN target_status t ON t.ProdCode=m.ProdCode
 JOIN providers p ON p.ProdCode=m.ProdCode AND p.ProviderCategory=t.ProviderCategory
 AND (t.PracType IS NULL OR t.PracType=p.PracType) AND p.Located

 GROUP BY ALL
)
SELECT m.AddressKey,m.ProdCode,m.MemberCount,m.Province,m.District,m.Geotype,m.LocationStatus,
 t.ProviderCategory,t.Discipline,s.RadiusKm,d.NearestKm,
 t.ListedProviders,t.UnlocatedProviders,
 CASE WHEN m.LocationStatus<>'READY' THEN m.LocationStatus
      WHEN s.RadiusKm IS NULL THEN 'STANDARD_MISSING'
      WHEN t.ListedProviders=0 THEN 'PRODUCT_DIRECTORY_MISSING'
      WHEN d.NearestKm IS NULL THEN 'PROVIDER_COORDINATES_MISSING'
      ELSE 'MAPPED_DIRECTORY_ESTIMATE' END AS AssessmentStatus,
 CASE WHEN m.LocationStatus='READY' AND s.RadiusKm IS NOT NULL AND d.NearestKm IS NOT NULL
      THEN CASE WHEN d.NearestKm<=s.RadiusKm THEN 1 ELSE 0 END END AS WithinStandard
FROM hive_metastore.geomap.MemberLocationPlanning m
JOIN target_status t ON t.ProdCode=m.ProdCode
LEFT JOIN measured d ON d.Latitude=m.Latitude AND d.Longitude=m.Longitude AND d.ProdCode=m.ProdCode
 AND d.ProviderCategory=t.ProviderCategory AND d.Discipline=t.Discipline
LEFT JOIN hive_metastore.geomap.AccessStandard s ON s.ProviderCategory=t.ProviderCategory AND s.Geotype=m.Geotype;
