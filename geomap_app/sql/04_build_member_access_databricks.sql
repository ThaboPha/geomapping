-- Superseded by 05_member_population_pipeline.sql (weighted aggregate MemberLocation contract).
-- This legacy per-beneficiary template is reference only; do not run against the new MemberLocation.
-- Databricks adaptation of original Script 02 section 2.
-- REQUIRED INPUT (not created or fabricated by this script):
-- hive_metastore.geomap.MemberLocation with one current row per pseudonymised
-- beneficiary: MemberKey, ProdCode, Province, District, Geotype, Latitude,
-- Longitude, MatchLevel. MemberKey must distinguish dependants.
-- Populate from current membership_live addresses through verified geocoding
-- and boundary/classification joins before running this script.
-- No member names or addresses are included in the output.

SELECT assert_true(count(*) > 0, 'MemberLocation must contain geocoded member locations')
FROM hive_metastore.geomap.MemberLocation;

SELECT assert_true(count(*) = count(DISTINCT MemberKey), 'MemberKey must uniquely identify each current beneficiary')
FROM hive_metastore.geomap.MemberLocation;

CREATE OR REPLACE VIEW hive_metastore.geomap.MemberAccess AS
WITH targets AS (
  SELECT 'GP' AS ProviderCategory, CAST(NULL AS INT) AS PracType, 'GP' AS Discipline
  UNION ALL SELECT 'Hospital', CAST(NULL AS INT), 'Network hospital'
  UNION ALL SELECT DISTINCT ProviderCategory, PracType, PracTypeDescr
  FROM hive_metastore.geomap.ProviderCategory
  WHERE ProviderCategory IN ('Core Specialist', 'Other Specialist')
), providers AS (
  SELECT DISTINCT trim(n.ProdCode) AS ProdCode, p.PracNum, p.ProviderCategory,
    p.PracType, g.Latitude, g.Longitude,
    g.Latitude BETWEEN -35 AND -22 AND g.Longitude BETWEEN 16 AND 33.5 AS Located
  FROM hive_metastore.geomap.ProductNetworkProvider n
  JOIN hive_metastore.geomap.ProviderMaster p ON p.PracNum = n.PracNum
  LEFT JOIN hive_metastore.geomap.PracticeGeocode g ON g.PracNum = p.PracNum
  -- Unknown assignment status is included as a network candidate; this does
  -- not confirm referral eligibility or individual cover.
  WHERE CAST(n.AssBlockActive AS INT) = 0 OR n.AssBlockActive IS NULL
), distances AS (
  SELECT m.MemberKey, trim(m.ProdCode) AS ProdCode, m.Province, m.District,
    m.Geotype, t.ProviderCategory, t.Discipline,
    count(p.PracNum) AS ListedProviders,
    count_if(p.PracNum IS NOT NULL AND NOT coalesce(p.Located, false)) AS UnlocatedProviders,
    min(CASE WHEN p.Located THEN 6371.0088 * 2 * asin(sqrt(least(1.0,
      pow(sin(radians(p.Latitude - m.Latitude) / 2), 2)
      + cos(radians(m.Latitude)) * cos(radians(p.Latitude))
      * pow(sin(radians(p.Longitude - m.Longitude) / 2), 2)))) END) AS NearestKm
  FROM hive_metastore.geomap.MemberLocation m
  CROSS JOIN targets t
  LEFT JOIN providers p ON p.ProdCode = trim(m.ProdCode)
    AND p.ProviderCategory = t.ProviderCategory
    AND (t.PracType IS NULL OR p.PracType = t.PracType)
  WHERE m.Latitude BETWEEN -35 AND -22 AND m.Longitude BETWEEN 16 AND 33.5
    AND m.Geotype IN ('Metro', 'Urban', 'Rural')
    AND nullif(trim(m.Province), '') IS NOT NULL
    AND nullif(trim(m.District), '') IS NOT NULL
  GROUP BY m.MemberKey, trim(m.ProdCode), m.Province, m.District,
    m.Geotype, t.ProviderCategory, t.Discipline
)
SELECT d.MemberKey, d.ProdCode, d.Province, d.District, d.Geotype,
  d.ProviderCategory, d.Discipline, s.RadiusKm, d.NearestKm,
  CASE WHEN d.NearestKm <= s.RadiusKm THEN 1 ELSE 0 END AS WithinStandard,
  d.ListedProviders, d.UnlocatedProviders,
  'Assessed' AS AssessmentStatus,
  'Straight-line distance; network candidates; confirm cover' AS MeasurementNote
FROM distances d
JOIN hive_metastore.geomap.AccessStandard s
  ON s.ProviderCategory = d.ProviderCategory AND s.Geotype = d.Geotype
-- Exclude incomplete provider targets rather than treat unmapped practices
-- as absent. Coverage denominators are assessed members only.
WHERE d.UnlocatedProviders = 0;

-- Readiness and denominator checks: compare these counts with the member
-- population. Missing targets must be reported as unassessed in analytics.
SELECT ProdCode, ProviderCategory, Discipline, Geotype, count(*) AS AssessedMembers
FROM hive_metastore.geomap.MemberAccess GROUP BY ALL;

SELECT Province, District, Geotype AS Area, ProviderCategory, Discipline,
  count(*) AS Members, sum(1 - WithinStandard) AS MembersOutside,
  round(100.0 * sum(1 - WithinStandard) / count(*), 1) AS PercentOutside
FROM hive_metastore.geomap.MemberAccess GROUP BY ALL;
