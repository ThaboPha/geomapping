-- Aggregated membership geography pipeline. No source objects are changed.
-- Restricted address views remain in geomap_private; the app reads only counts.
CREATE SCHEMA IF NOT EXISTS hive_metastore.geomap_private;

CREATE TABLE IF NOT EXISTS hive_metastore.geomap_private.AddressGeocode (
 AddressKey STRING, Latitude DOUBLE, Longitude DOUBLE, Province STRING,
 District STRING, Geotype STRING, MatchLevel STRING, Confidence DOUBLE,
 Source STRING, Status STRING, GeocodedAt TIMESTAMP
) USING DELTA;

CREATE OR REPLACE VIEW hive_metastore.geomap_private.MemberAddressPopulation AS
            WITH profiles AS (
                SELECT MemNum, BenfcNum, BenfcStat, BenfcEndDate
                FROM hive_metastore.membership_live.benfcprof_bronze
                WHERE EffDate <= CURRENT_TIMESTAMP()
                QUALIFY row_number() OVER (PARTITION BY MemNum, BenfcNum
                    ORDER BY EffDate DESC, BenfcProfAsAt DESC, _ingestion_timestamp DESC) = 1
            ), subscriptions AS (
                SELECT MemNum, trim(ProdCode) AS ProdCode, Active
                FROM hive_metastore.membership_live.v_memsubsctrl
                WHERE EffDate <= CURRENT_TIMESTAMP()
                    AND (EffTo IS NULL OR EffTo >= CURRENT_TIMESTAMP())
                QUALIFY row_number() OVER (PARTITION BY MemNum
                    ORDER BY EffDate DESC, SubsCtrlAsAt DESC) = 1
            ), addresses AS (
                SELECT MemNum, BenfcNum, trim(Town) AS Town, trim(PostCode) AS PostCode,
                    trim(Line1) AS Line1, trim(Line2) AS Line2, trim(Line3) AS Line3,
                    upper(trim(CntryCode)) AS CountryCode,
                    upper(trim(AddrType)) AS AddrType
                FROM hive_metastore.membership_live.benfcaddr_bronze
                WHERE EffDate <= CURRENT_TIMESTAMP() AND upper(trim(AddrType)) IN ('R', 'S', 'P')
                QUALIFY row_number() OVER (PARTITION BY MemNum, BenfcNum
                    ORDER BY CASE WHEN upper(trim(AddrType)) IN ('R','S') THEN 0 ELSE 1 END,
                        EffDate DESC, _ingestion_timestamp DESC, TimeStamp DESC) = 1
            ), accounts AS (
                SELECT MemNum, trim(Town) AS Town, trim(PostCode) AS PostCode,
                    trim(Line1) AS Line1, trim(Line2) AS Line2, trim(Line3) AS Line3,
                    upper(trim(CntryCode)) AS CountryCode,
                    upper(trim(AddrType)) AS AddrType
                FROM hive_metastore.membership_live.memaddr_bronze
                WHERE EffDate <= CURRENT_TIMESTAMP() AND upper(trim(AddrType)) IN ('R', 'S', 'P')
                QUALIFY row_number() OVER (PARTITION BY MemNum
                    ORDER BY CASE WHEN upper(trim(AddrType)) IN ('R','S') THEN 0 ELSE 1 END,
                        EffDate DESC, _ingestion_timestamp DESC, TimeStamp DESC) = 1

            ), selected AS (
              SELECT s.ProdCode,
                coalesce(a.Line1,m.Line1) AS Line1, coalesce(a.Line2,m.Line2) AS Line2,
                coalesce(a.Line3,m.Line3) AS Line3, coalesce(a.Town,m.Town) AS Town,
                coalesce(a.PostCode,m.PostCode) AS PostCode,
                coalesce(a.CountryCode,m.CountryCode) AS CountryCode,
                coalesce(a.AddrType,m.AddrType,'Unknown') AS AddressType
              FROM profiles p JOIN subscriptions s ON s.MemNum=p.MemNum
              LEFT JOIN addresses a ON a.MemNum=p.MemNum AND a.BenfcNum=p.BenfcNum
              LEFT JOIN accounts m ON m.MemNum=p.MemNum AND a.MemNum IS NULL
              WHERE upper(trim(p.BenfcStat))='A'
                AND (p.BenfcEndDate IS NULL OR p.BenfcEndDate>=CURRENT_TIMESTAMP())
                AND coalesce(s.Active,true) AND nullif(s.ProdCode,'') IS NOT NULL
            ), normalised AS (
              SELECT ProdCode, AddressType,
                upper(regexp_replace(trim(coalesce(Line1,'')), '\\s+', ' ')) AS Line1,
                upper(regexp_replace(trim(coalesce(Line2,'')), '\\s+', ' ')) AS Line2,
                upper(regexp_replace(trim(coalesce(Line3,'')), '\\s+', ' ')) AS Line3,
                upper(regexp_replace(trim(coalesce(Town,'')), '\\s+', ' ')) AS Town,
                trim(coalesce(PostCode,'')) AS PostCode,
                upper(trim(coalesce(CountryCode,''))) AS CountryCode
              FROM selected
            )
SELECT sha2(to_json(named_struct('Line1',Line1,'Line2',Line2,'Line3',Line3,
 'Town',Town,'PostCode',PostCode,'CountryCode',CountryCode,'AddressType',AddressType)),256) AS AddressKey,
 ProdCode, AddressType, Line1, Line2, Line3, Town, PostCode, CountryCode,
 count(*) AS MemberCount
FROM normalised GROUP BY ALL;

CREATE OR REPLACE VIEW hive_metastore.geomap_private.MemberGeocodingQueue AS
SELECT p.AddressKey, p.AddressType, p.Line1, p.Line2, p.Line3, p.Town, p.PostCode,
 p.CountryCode, sum(p.MemberCount) AS Members,
 CASE WHEN p.AddressType NOT IN ('R','S') THEN 'NON_RESIDENTIAL'
      WHEN p.CountryCode NOT IN ('','ZA','ZAF','RSA','SA') THEN 'OUTSIDE_SUPPORTED_COUNTRY'
      WHEN concat_ws('',p.Line1,p.Line2,p.Line3,p.Town,p.PostCode)='' THEN 'MISSING_ADDRESS'
      ELSE 'READY' END AS QueueStatus
FROM hive_metastore.geomap_private.MemberAddressPopulation p
LEFT JOIN hive_metastore.geomap_private.AddressGeocode g ON g.AddressKey=p.AddressKey
WHERE g.AddressKey IS NULL
GROUP BY ALL;

-- Internal-only area estimates. Never submit member addresses externally.
-- Only one reference coordinate and province is allowed per locality/postcode.
MERGE INTO hive_metastore.geomap_private.AddressGeocode target
USING (
 WITH reference AS (
   SELECT lower(trim(Place)) AS Locality, trim(PostCode) AS PostCode,
     max(CAST(Latitude AS DOUBLE)) AS Latitude, max(CAST(Longitude AS DOUBLE)) AS Longitude,
     max(Province) AS Province
   FROM hive_metastore.geomap.PlaceCentroid
   WHERE Latitude BETWEEN -35 AND -22 AND Longitude BETWEEN 16 AND 33.5
   GROUP BY lower(trim(Place)),trim(PostCode)
   HAVING count(DISTINCT struct(Latitude,Longitude))=1 AND count(DISTINCT Province)=1
 )
 SELECT DISTINCT q.AddressKey,r.Latitude,r.Longitude,r.Province
 FROM hive_metastore.geomap_private.MemberGeocodingQueue q
 JOIN reference r ON lower(trim(q.Town))=r.Locality AND trim(q.PostCode)=r.PostCode
 WHERE q.QueueStatus='READY'
) source ON source.AddressKey=target.AddressKey
WHEN NOT MATCHED THEN INSERT (AddressKey,Latitude,Longitude,Province,District,Geotype,
 MatchLevel,Confidence,Source,Status,GeocodedAt)
VALUES (source.AddressKey,source.Latitude,source.Longitude,source.Province,'Unknown','Unknown',
 'Provisional provider-derived area centroid',NULL,'Existing GeoMap PlaceCentroid','MATCHED',current_timestamp());

CREATE TABLE IF NOT EXISTS hive_metastore.geomap_private.CoordinateClassification (
 Latitude DOUBLE, Longitude DOUBLE, Province STRING, District STRING, Geotype STRING,
 Source STRING, ClassifiedAt TIMESTAMP
) USING DELTA;

CREATE OR REPLACE VIEW hive_metastore.geomap.MemberLocation AS
SELECT p.AddressKey, p.ProdCode, p.AddressType, sum(p.MemberCount) AS MemberCount,
 coalesce(nullif(g.Province,'Unknown'),c.Province,'Unknown') AS Province, coalesce(nullif(g.District,'Unknown'),c.District,'Unknown') AS District,
 coalesce(nullif(g.Geotype,'Unknown'),c.Geotype,'Unknown') AS Geotype, g.Latitude, g.Longitude, g.MatchLevel,
 CASE WHEN p.AddressType NOT IN ('R','S') THEN 'NON_RESIDENTIAL'
      WHEN p.CountryCode NOT IN ('','ZA','ZAF','RSA','SA') THEN 'OUTSIDE_SUPPORTED_COUNTRY'
      WHEN g.Status='MATCHED' AND g.Latitude BETWEEN -35 AND -22 AND g.Longitude BETWEEN 16 AND 33.5
         AND coalesce(nullif(g.Geotype,'Unknown'),c.Geotype) IN ('Metro','Urban','Rural')
         AND nullif(coalesce(nullif(g.Province,'Unknown'),c.Province),'') IS NOT NULL AND coalesce(nullif(g.Province,'Unknown'),c.Province) <> 'Unknown'
         AND nullif(coalesce(nullif(g.District,'Unknown'),c.District),'') IS NOT NULL AND coalesce(nullif(g.District,'Unknown'),c.District) <> 'Unknown'
         AND g.MatchLevel NOT LIKE 'Provisional%'
        THEN 'READY'
      WHEN g.Status='MATCHED' AND g.MatchLevel LIKE 'Provisional%' THEN 'AREA_COORDINATES_REQUIRE_VERIFICATION'
      WHEN g.Status='MATCHED' THEN 'GEOGRAPHY_REQUIRES_CLASSIFICATION'
      ELSE 'GEOCODING_REQUIRED' END AS LocationStatus
FROM hive_metastore.geomap_private.MemberAddressPopulation p
LEFT JOIN hive_metastore.geomap_private.AddressGeocode g ON g.AddressKey=p.AddressKey
LEFT JOIN hive_metastore.geomap_private.CoordinateClassification c ON c.Latitude=g.Latitude AND c.Longitude=g.Longitude
GROUP BY ALL;

CREATE OR REPLACE VIEW hive_metastore.geomap.MemberAccess AS
WITH targets AS (
 SELECT 'GP' AS ProviderCategory, CAST(NULL AS INT) AS PracType, 'GP' AS Discipline
 UNION ALL SELECT 'Hospital', CAST(NULL AS INT), 'Network hospital'
 UNION ALL SELECT DISTINCT ProviderCategory, PracType, PracTypeDescr
 FROM hive_metastore.geomap.ProviderCategory
 WHERE ProviderCategory IN ('Core Specialist','Other Specialist')
), providers AS (
 SELECT DISTINCT trim(n.ProdCode) AS ProdCode, p.PracNum, p.ProviderCategory, p.PracType,
 g.Latitude, g.Longitude,
 coalesce(g.Latitude BETWEEN -35 AND -22 AND g.Longitude BETWEEN 16 AND 33.5,false) AS Located
 FROM hive_metastore.geomap.ProductNetworkProvider n
 JOIN hive_metastore.geomap.ProviderMaster p ON p.PracNum=n.PracNum
 LEFT JOIN hive_metastore.geomap.PracticeGeocode g ON g.PracNum=p.PracNum
 WHERE CAST(n.AssBlockActive AS INT)=0 OR n.AssBlockActive IS NULL
), provider_status AS (
 SELECT ProdCode,ProviderCategory,PracType,count(*) AS Providers,
 count_if(NOT Located) AS Unlocated FROM providers GROUP BY ALL
), target_status AS (
 SELECT codes.ProdCode,t.ProviderCategory,t.PracType,t.Discipline,
 coalesce(sum(p.Providers),0) AS ListedProviders,coalesce(sum(p.Unlocated),0) AS UnlocatedProviders
 FROM (SELECT DISTINCT ProdCode FROM hive_metastore.geomap.MemberLocation) codes
 CROSS JOIN targets t LEFT JOIN provider_status p ON p.ProdCode=codes.ProdCode
 AND p.ProviderCategory=t.ProviderCategory AND (t.PracType IS NULL OR t.PracType=p.PracType)
 GROUP BY ALL
), measured AS (
 SELECT m.Latitude,m.Longitude,m.ProdCode,t.ProviderCategory,t.Discipline,
 min(6371.0088*2*asin(sqrt(least(1.0,
 pow(sin(radians(p.Latitude-m.Latitude)/2),2)+cos(radians(m.Latitude))*cos(radians(p.Latitude))
 *pow(sin(radians(p.Longitude-m.Longitude)/2),2))))) AS NearestKm
 FROM (SELECT DISTINCT ProdCode,Latitude,Longitude FROM hive_metastore.geomap.MemberLocation WHERE LocationStatus='READY') m
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
      WHEN t.UnlocatedProviders>0 THEN 'PROVIDER_COORDINATES_MISSING'
      WHEN t.ListedProviders=0 THEN 'NO_NETWORK_PROVIDERS'
      ELSE 'ASSESSED' END AS AssessmentStatus,
 CASE WHEN m.LocationStatus='READY' AND s.RadiusKm IS NOT NULL AND t.UnlocatedProviders=0
      THEN CASE WHEN d.NearestKm<=s.RadiusKm THEN 1 ELSE 0 END END AS WithinStandard
FROM hive_metastore.geomap.MemberLocation m
JOIN target_status t ON t.ProdCode=m.ProdCode
LEFT JOIN measured d ON d.Latitude=m.Latitude AND d.Longitude=m.Longitude AND d.ProdCode=m.ProdCode
 AND d.ProviderCategory=t.ProviderCategory AND d.Discipline=t.Discipline
LEFT JOIN hive_metastore.geomap.AccessStandard s ON s.ProviderCategory=t.ProviderCategory AND s.Geotype=m.Geotype;
