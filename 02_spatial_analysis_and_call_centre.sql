/* =====================================================================================
   BONITAS GEO-MAPPING PROJECT
   Script 02 - Spatial Analysis and Call Centre Lookup (run AFTER geocoding)
   Version : 2026-10-09

   Prerequisites
     - Script 01 has run.
     - GeoMap.PracticeGeocode is loaded and GeoPoint is populated.
     - For Section 2: GeoMap.MemberLocation is loaded (pseudonymised; see DDL below).

   Sections
     1. Specialist -> nearest network hospital alignment
     2. Member coverage against access standards + coverage curve (radius calibration)
     3. Call centre stored procedure: nearest network providers for an option
   ===================================================================================== */

SET NOCOUNT ON;

/* -------------------------------------------------------------------------------------
   1. SPECIALIST TO NETWORK HOSPITAL ALIGNMENT (location lens)
      Nearest network hospital that serves at least one product the specialist serves.
      "On-site" is only claimed for street-level geocodes.
      The behaviour lens (where they actually admit) needs claims data - next phase.
   ------------------------------------------------------------------------------------- */
DROP TABLE IF EXISTS GeoMap.SpecialistHospitalAlignment;

SELECT
    s.PracNum,
    s.PracNumDisplay,
    s.PracName,
    s.PracTypeDescr,
    s.ProviderCategory,
    s.ProvinceDescr,
    s.NetworkNames,
    sg.MatchLevel                AS SpecialistMatchLevel,
    h.HospPracNum,
    h.HospName,
    h.HospMatchLevel,
    h.DistanceKm,
    CASE
        WHEN sg.GeoPoint IS NULL                                   THEN 'Not geocoded'
        WHEN h.HospPracNum IS NULL                                 THEN 'No network hospital on shared options'
        WHEN h.DistanceKm <= 0.5 AND sg.MatchLevel = 'Street'
                                 AND h.HospMatchLevel = 'Street'   THEN 'On-site / adjacent'
        WHEN h.DistanceKm <= 5                                     THEN 'Near (<= 5 km)'
        ELSE                                                            'Distant (> 5 km)'
    END AS LocationAlignment
INTO GeoMap.SpecialistHospitalAlignment
FROM      GeoMap.ProviderMaster  s
LEFT JOIN GeoMap.PracticeGeocode sg ON sg.PracNum = s.PracNum
OUTER APPLY
(
    SELECT TOP (1)
           hm.PracNum     AS HospPracNum,
           hm.PracName    AS HospName,
           hg.MatchLevel  AS HospMatchLevel,
           CAST(hg.GeoPoint.STDistance(sg.GeoPoint) / 1000.0 AS decimal(8,2)) AS DistanceKm
    FROM   GeoMap.ProviderMaster  hm
    JOIN   GeoMap.PracticeGeocode hg ON hg.PracNum = hm.PracNum
    WHERE  hm.ProviderCategory  = 'Hospital'
      AND  hm.IsNetworkProvider = 1
      AND  hg.GeoPoint IS NOT NULL
      AND  sg.GeoPoint IS NOT NULL
      AND  EXISTS (SELECT 1
                   FROM   GeoMap.ProductNetworkProvider a
                   JOIN   GeoMap.ProductNetworkProvider b ON b.ProdCode = a.ProdCode
                   WHERE  a.PracNum = s.PracNum
                     AND  b.PracNum = hm.PracNum)
    ORDER  BY hg.GeoPoint.STDistance(sg.GeoPoint)
) h
WHERE s.IsNetworkProvider = 1
  AND s.ProviderCategory IN ('Core Specialist', 'Other Specialist', 'Hospital-based Specialist');

-- 1a. Alignment summary by discipline.
SELECT PracTypeDescr, LocationAlignment, COUNT(*) AS Specialists
FROM   GeoMap.SpecialistHospitalAlignment
GROUP  BY PracTypeDescr, LocationAlignment
ORDER  BY PracTypeDescr, LocationAlignment;

-- 1b. Discipline coverage per network hospital: which core disciplines have no
--     contracted specialist on-site or within 5 km?
WITH HospitalDiscipline AS
(
    SELECT HospPracNum, HospName, PracTypeDescr, COUNT(*) AS Specialists
    FROM   GeoMap.SpecialistHospitalAlignment
    WHERE  LocationAlignment IN ('On-site / adjacent', 'Near (<= 5 km)')
    GROUP  BY HospPracNum, HospName, PracTypeDescr
)
SELECT h.PracNum AS HospPracNum, h.PracName AS HospName, d.PracTypeDescr AS Discipline,
       ISNULL(hd.Specialists, 0) AS ContractedSpecialistsNearby
FROM   GeoMap.ProviderMaster h
CROSS JOIN (SELECT DISTINCT PracTypeDescr
            FROM   GeoMap.ProviderCategory
            WHERE  ProviderCategory IN ('Core Specialist', 'Hospital-based Specialist')) d
LEFT JOIN HospitalDiscipline hd ON hd.HospPracNum = h.PracNum AND hd.PracTypeDescr = d.PracTypeDescr
WHERE  h.ProviderCategory = 'Hospital' AND h.IsNetworkProvider = 1
ORDER  BY ContractedSpecialistsNearby, h.PracName, d.PracTypeDescr;

-- 1c. Recruitment targets: NON-network specialists on-site at a network hospital.
SELECT s.PracNumDisplay, s.PracName, s.PracTypeDescr, s.ProvinceDescr,
       h.PracName AS NetworkHospital,
       CAST(hg.GeoPoint.STDistance(sg.GeoPoint) / 1000.0 AS decimal(8,2)) AS DistanceKm
FROM   GeoMap.ProviderMaster  s
JOIN   GeoMap.PracticeGeocode sg ON sg.PracNum = s.PracNum AND sg.MatchLevel = 'Street'
JOIN   GeoMap.ProviderMaster  h  ON h.ProviderCategory = 'Hospital' AND h.IsNetworkProvider = 1
JOIN   GeoMap.PracticeGeocode hg ON hg.PracNum = h.PracNum AND hg.MatchLevel = 'Street'
WHERE  s.IsNetworkProvider = 0
  AND  s.ProviderCategory IN ('Core Specialist', 'Other Specialist', 'Hospital-based Specialist')
  AND  hg.GeoPoint.STDistance(sg.GeoPoint) <= 500
ORDER  BY h.PracName, s.PracTypeDescr;


/* -------------------------------------------------------------------------------------
   2. MEMBER COVERAGE
      GeoMap.MemberLocation is loaded from a pseudonymised member extract.
      Geotype (Metro | Urban | Rural) comes from a spatial join to Stats SA boundaries
      (8 metros = Metro; other urban = Urban; traditional / farm = Rural).

      CREATE TABLE GeoMap.MemberLocation
      (
          MemberKey   varbinary(32) NOT NULL PRIMARY KEY,  -- SHA-256 of member number + salt
          ProdCode    char(5)       NOT NULL,
          Province    varchar(50)   NULL,
          District    varchar(100)  NULL,
          Geotype     varchar(10)   NOT NULL,
          MatchLevel  varchar(20)   NULL,
          GeoPoint    geography     NULL
      );

      Performance: members x targets nearest-neighbour searches are heavy.
      Run per province, or compute nearest distances in Python (BallTree) and load
      them into GeoMap.MemberAccess instead.
   ------------------------------------------------------------------------------------- */
IF OBJECT_ID('GeoMap.MemberLocation') IS NOT NULL
BEGIN
    DROP TABLE IF EXISTS GeoMap.MemberAccess;

    WITH AccessTarget AS
    (
        -- GP and hospital: any provider in the category
        SELECT 'GP' AS ProviderCategory, CAST(NULL AS int) AS PracType, CAST('GP' AS varchar(100)) AS Discipline
        UNION ALL
        SELECT 'Hospital', NULL, 'Network hospital'
        UNION ALL
        -- Specialists: measured per discipline
        SELECT ProviderCategory, PracType, PracTypeDescr
        FROM   GeoMap.ProviderCategory
        WHERE  ProviderCategory IN ('Core Specialist', 'Other Specialist')
    )
    SELECT m.MemberKey,
           m.ProdCode,
           m.Province,
           m.District,
           m.Geotype,
           t.ProviderCategory,
           t.Discipline,
           s.RadiusKm,
           n.NearestKm,
           CASE WHEN n.NearestKm <= s.RadiusKm THEN 1 ELSE 0 END AS WithinStandard
    INTO   GeoMap.MemberAccess
    FROM   GeoMap.MemberLocation m
    CROSS JOIN AccessTarget t
    JOIN   GeoMap.AccessStandard s ON s.ProviderCategory = t.ProviderCategory
                                  AND s.Geotype          = m.Geotype
    OUTER APPLY
    (
        SELECT TOP (1)
               CAST(g.GeoPoint.STDistance(m.GeoPoint) / 1000.0 AS decimal(8,2)) AS NearestKm
        FROM   GeoMap.ProductNetworkProvider pnp
        JOIN   GeoMap.ProviderMaster         pm ON pm.PracNum = pnp.PracNum
        JOIN   GeoMap.PracticeGeocode        g  ON g.PracNum  = pnp.PracNum
        WHERE  pnp.ProdCode = m.ProdCode
          AND  pm.ProviderCategory = t.ProviderCategory
          AND (t.PracType IS NULL OR pm.PracType = t.PracType)
          AND  g.GeoPoint IS NOT NULL
        ORDER  BY g.GeoPoint.STDistance(m.GeoPoint)
    ) n
    WHERE m.GeoPoint IS NOT NULL;

    -- 2a. Coverage vs proposed standard, with distance percentiles.
    SELECT DISTINCT
           ProdCode, Geotype, ProviderCategory, Discipline, RadiusKm,
           COUNT(*)            OVER (PARTITION BY ProdCode, Geotype, ProviderCategory, Discipline) AS Members,
           CAST(100.0 * SUM(WithinStandard) OVER (PARTITION BY ProdCode, Geotype, ProviderCategory, Discipline)
                / COUNT(*)     OVER (PARTITION BY ProdCode, Geotype, ProviderCategory, Discipline) AS decimal(5,1)) AS PctWithinStandard,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY NearestKm)
                               OVER (PARTITION BY ProdCode, Geotype, ProviderCategory, Discipline) AS MedianKm,
           PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY NearestKm)
                               OVER (PARTITION BY ProdCode, Geotype, ProviderCategory, Discipline) AS P90Km
    FROM   GeoMap.MemberAccess
    ORDER  BY ProdCode, Geotype, ProviderCategory, Discipline;

    -- 2b. Coverage curve: % of members within each distance band.
    --     Use this to calibrate GeoMap.AccessStandard before presenting to the Scheme.
    SELECT ProviderCategory, Discipline, Geotype,
           COUNT(*) AS Members,
           CAST(100.0 * SUM(CASE WHEN NearestKm <=   5 THEN 1 ELSE 0 END) / COUNT(*) AS decimal(5,1)) AS Pct_5km,
           CAST(100.0 * SUM(CASE WHEN NearestKm <=  10 THEN 1 ELSE 0 END) / COUNT(*) AS decimal(5,1)) AS Pct_10km,
           CAST(100.0 * SUM(CASE WHEN NearestKm <=  15 THEN 1 ELSE 0 END) / COUNT(*) AS decimal(5,1)) AS Pct_15km,
           CAST(100.0 * SUM(CASE WHEN NearestKm <=  20 THEN 1 ELSE 0 END) / COUNT(*) AS decimal(5,1)) AS Pct_20km,
           CAST(100.0 * SUM(CASE WHEN NearestKm <=  30 THEN 1 ELSE 0 END) / COUNT(*) AS decimal(5,1)) AS Pct_30km,
           CAST(100.0 * SUM(CASE WHEN NearestKm <=  50 THEN 1 ELSE 0 END) / COUNT(*) AS decimal(5,1)) AS Pct_50km,
           CAST(100.0 * SUM(CASE WHEN NearestKm <= 100 THEN 1 ELSE 0 END) / COUNT(*) AS decimal(5,1)) AS Pct_100km,
           CAST(100.0 * SUM(CASE WHEN NearestKm <= 200 THEN 1 ELSE 0 END) / COUNT(*) AS decimal(5,1)) AS Pct_200km
    FROM   GeoMap.MemberAccess
    GROUP  BY ProviderCategory, Discipline, Geotype
    ORDER  BY ProviderCategory, Discipline, Geotype;

    -- 2c. Gap hotspots: districts with the most members outside the standard.
    SELECT TOP (50) Province, District, ProviderCategory, Discipline,
           SUM(1 - WithinStandard) AS MembersOutsideStandard,
           COUNT(*)                AS Members
    FROM   GeoMap.MemberAccess
    GROUP  BY Province, District, ProviderCategory, Discipline
    ORDER  BY MembersOutsideStandard DESC;
END;
GO


/* -------------------------------------------------------------------------------------
   3. CALL CENTRE LOOKUP
      Nearest network providers for the member's option, from a point (member address
      or any address the agent geocodes). Feed this into Power BI / CRM.

      EXEC GeoMap.usp_FindNearestNetworkProviders
           @ProdCode = 'XXXXX', @Latitude = -26.1076, @Longitude = 28.0567,
           @ProviderCategory = 'GP';
   ------------------------------------------------------------------------------------- */
CREATE OR ALTER PROCEDURE GeoMap.usp_FindNearestNetworkProviders
    @ProdCode          char(5),
    @Latitude          decimal(9,6),
    @Longitude         decimal(9,6),
    @ProviderCategory  varchar(30)  = 'GP',
    @PracType          int          = NULL,   -- optional: a specific discipline
    @MaxKm             decimal(6,1) = 50,
    @MaxResults        int          = 10
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @Point geography = geography::Point(@Latitude, @Longitude, 4326);

    WITH Eligible AS
    (
        SELECT pnp.PracNum,
               STRING_AGG(CAST(pnp.NetworkName AS varchar(max)), '; ') AS Networks,
               MAX(CAST(pnp.PrimaryNetworkInd AS int))                 AS PrimaryNetworkInd,
               MAX(pnp.AssBlockActive)                                 AS AssBlockActive
        FROM   GeoMap.ProductNetworkProvider pnp
        WHERE  pnp.ProdCode = @ProdCode
        GROUP  BY pnp.PracNum
    )
    SELECT TOP (@MaxResults)
           pm.PracNumDisplay,
           pm.PracName,
           pm.PracTypeDescr,
           pm.DisplayAddress,
           pm.PracticeEmail,
           e.Networks,
           e.PrimaryNetworkInd,
           CAST(g.GeoPoint.STDistance(@Point) / 1000.0 AS decimal(6,1)) AS DistanceKm,
           g.MatchLevel,
           g.Latitude,
           g.Longitude
    FROM   Eligible               e
    JOIN   GeoMap.ProviderMaster  pm ON pm.PracNum = e.PracNum
    JOIN   GeoMap.PracticeGeocode g  ON g.PracNum  = e.PracNum
    WHERE  pm.ProviderCategory = @ProviderCategory
      AND (@PracType IS NULL OR pm.PracType = @PracType)
      AND  e.AssBlockActive = 0
      AND  g.GeoPoint IS NOT NULL
      AND  g.GeoPoint.STDistance(@Point) <= @MaxKm * 1000
    ORDER  BY g.GeoPoint.STDistance(@Point);
END;
GO
