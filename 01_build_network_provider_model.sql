/* =====================================================================================
   BONITAS GEO-MAPPING PROJECT
   Script 01 - Network Provider Model (run BEFORE geocoding)
   Version : 2026-10-09

   Purpose
     Builds a clean, one-row-per-practice provider master enriched with network
     membership per product (benefit option) and discipline, using the i2core
     Network data context:

       Prac --< PracPracGrp >-- PracGrpMast --< NetworkPracGrp >-- NetworkMast
                                    |
                                    +--< PracTypePracGrp      (types allowed in group)
                                    +--< PracGrpProd          (group used on product, primary network flag)
                                    +--< ProdBenPracTypePracGrp (product + benefit term + practice type -> group)
                                    +--< PracGrpAssBlock      (assignment block periods)

   Run in a reporting / analytics database, NOT in i2core production.
   Source tables are referenced as i2core.dbo.<table>; adjust if needed.

   Sections
     0. Parameters and schema
     1. Configuration: provider categories and proposed access standards
     2. Active practices and active network membership
     3. Network eligibility per product (option) and practice type
     4. Provider master (geocoding-ready)
     5. Geocode store and geocoding queue
     6. Data quality checks

   ASSUMPTIONS TO VERIFY (marked "VERIFY" in the code)
     A1  PracType codes for GP / specialist / hospital categories (Section 1).
     A2  PracPracGrp has no effective dates: membership = row exists.
     A3  BenTermAsAt identifies the benefit term; latest term on/before @AsAt is current.
     A4  PracGrpAssBlock = period in which a practice group is blocked; flagged, not excluded.
     A5  Prac may hold several versions per PracNum; latest active version is used.
   ===================================================================================== */

SET NOCOUNT ON;

IF SCHEMA_ID('GeoMap') IS NULL EXEC('CREATE SCHEMA GeoMap');

/* -------------------------------------------------------------------------------------
   0. PARAMETERS
   ------------------------------------------------------------------------------------- */
DECLARE @AsAt date = CAST(GETDATE() AS date);


/* -------------------------------------------------------------------------------------
   1. CONFIGURATION
   ------------------------------------------------------------------------------------- */

-- 1a. Provider category per practice type.
--     Seeded from PracTypeMast so every type appears; review all 'Unclassified' rows and
--     set them to 'Other Specialist', 'Allied / Other', etc.            VERIFY (A1)
IF OBJECT_ID('GeoMap.ProviderCategory') IS NULL
BEGIN
    CREATE TABLE GeoMap.ProviderCategory
    (
        PracType          int          NOT NULL PRIMARY KEY,
        PracTypeDescr     varchar(100) NULL,
        ProviderCategory  varchar(30)  NOT NULL
    );

    INSERT INTO GeoMap.ProviderCategory (PracType, PracTypeDescr, ProviderCategory)
    SELECT t.PracType,
           t.Descr,
           CASE
               WHEN t.PracType IN (14, 15)                 THEN 'GP'
               WHEN t.PracType IN (16, 18, 22, 28, 32, 42) THEN 'Core Specialist'          -- O&G, physician, psychiatry, orthopaedics, paediatrics, general surgery
               WHEN t.PracType IN (10)                     THEN 'Hospital-based Specialist' -- anaesthetist
               WHEN t.PracType IN (56, 57, 58)             THEN 'Hospital'
               WHEN t.PracType IN (77)                     THEN 'Day Hospital'
               ELSE 'Unclassified'
           END
    FROM i2core.dbo.PracTypeMast t;
END;

-- 1b. Proposed access standards (to be calibrated with the coverage curve in Script 02).
IF OBJECT_ID('GeoMap.AccessStandard') IS NULL
BEGIN
    CREATE TABLE GeoMap.AccessStandard
    (
        ProviderCategory   varchar(30)  NOT NULL,
        Geotype            varchar(10)  NOT NULL,   -- Metro | Urban | Rural
        RadiusKm           decimal(6,1) NOT NULL,
        TargetCoveragePct  decimal(5,2) NOT NULL,
        CONSTRAINT PK_AccessStandard PRIMARY KEY (ProviderCategory, Geotype)
    );

    INSERT INTO GeoMap.AccessStandard (ProviderCategory, Geotype, RadiusKm, TargetCoveragePct)
    VALUES ('GP',               'Metro',  10, 90), ('GP',               'Urban',  20, 90), ('GP',               'Rural',  40, 90),
           ('Core Specialist',  'Metro',  25, 85), ('Core Specialist',  'Urban',  50, 85), ('Core Specialist',  'Rural', 100, 85),
           ('Other Specialist', 'Metro',  50, 85), ('Other Specialist', 'Urban', 100, 85), ('Other Specialist', 'Rural', 200, 85),
           ('Hospital',         'Metro',  25, 85), ('Hospital',         'Urban',  50, 85), ('Hospital',         'Rural', 100, 85);
END;


/* -------------------------------------------------------------------------------------
   2. ACTIVE PRACTICES AND ACTIVE NETWORK MEMBERSHIP
   ------------------------------------------------------------------------------------- */

-- 2a. One current, active row per practice.                            VERIFY (A5)
DROP TABLE IF EXISTS #ActivePrac;

SELECT x.PracNum, x.PracName, x.PracType, x.EffDate, x.EffTo
INTO   #ActivePrac
FROM
(
    SELECT p.PracNum, p.PracName, p.PracType, p.EffDate, p.EffTo,
           ROW_NUMBER() OVER (PARTITION BY p.PracNum ORDER BY p.EffDate DESC) AS rn
    FROM   i2core.dbo.Prac p
    WHERE  p.EffDate <= @AsAt
) x
WHERE x.rn = 1
  AND (x.EffTo IS NULL OR x.EffTo >= @AsAt);

CREATE UNIQUE CLUSTERED INDEX IX_ActivePrac ON #ActivePrac (PracNum);

-- 2b. Active network <-> practice group links.
--     NetworkPracGrp is versioned twice: EffDate (business period) and
--     NetworkPracGrpAsAt (capture version). Take the latest version of the latest
--     period that started on/before @AsAt, then keep it only if it has not ended.
DROP TABLE IF EXISTS GeoMap.NetworkGroup;

SELECT x.NetworkCode,
       RTRIM(x.NetworkName)  AS NetworkName,
       x.PracGrpCode,
       RTRIM(x.PracGrpDescr) AS PracGrpDescr,
       x.CapInd,
       x.PCPInd,
       x.EffDate,
       x.EffTo,
       CASE WHEN EXISTS (SELECT 1
                         FROM   i2core.dbo.PracGrpAssBlock b
                         WHERE  b.PracGrpCode = x.PracGrpCode
                           AND  b.EffDate <= @AsAt
                           AND (b.EffTo IS NULL OR b.EffTo >= @AsAt))
            THEN 1 ELSE 0 END AS AssBlockActive                                -- VERIFY (A4)
INTO   GeoMap.NetworkGroup
FROM
(
    SELECT npg.NetworkCode, nm.NetworkName, npg.PracGrpCode, pgm.Descr AS PracGrpDescr,
           pgm.CapInd, pgm.PCPInd, npg.EffDate, npg.EffTo,
           ROW_NUMBER() OVER (PARTITION BY npg.NetworkCode, npg.PracGrpCode
                              ORDER BY npg.EffDate DESC, npg.NetworkPracGrpAsAt DESC) AS rn
    FROM   i2core.dbo.NetworkPracGrp npg
    JOIN   i2core.dbo.NetworkMast    nm  ON nm.NetworkCode  = npg.NetworkCode
    JOIN   i2core.dbo.PracGrpMast    pgm ON pgm.PracGrpCode = npg.PracGrpCode
    WHERE  npg.EffDate <= @AsAt
) x
WHERE x.rn = 1
  AND (x.EffTo IS NULL OR x.EffTo >= @AsAt);

-- 2c. Practice-level network membership.                                VERIFY (A2)
--     PracTypeRuleCheck tests the practice's type against PracTypePracGrp.
DROP TABLE IF EXISTS GeoMap.PracticeNetwork;

SELECT ppg.PracNum,
       ap.PracType,
       ng.NetworkCode,
       ng.NetworkName,
       ng.PracGrpCode,
       ng.PracGrpDescr,
       ng.CapInd,
       ng.PCPInd,
       ng.AssBlockActive,
       CASE
           WHEN NOT EXISTS (SELECT 1 FROM i2core.dbo.PracTypePracGrp r
                            WHERE r.PracGrpCode = ppg.PracGrpCode)                          THEN 'No type rule'
           WHEN EXISTS     (SELECT 1 FROM i2core.dbo.PracTypePracGrp r
                            WHERE r.PracGrpCode = ppg.PracGrpCode AND r.PracType = ap.PracType) THEN 'Allowed'
           ELSE 'Type not allowed'
       END AS PracTypeRuleCheck
INTO   GeoMap.PracticeNetwork
FROM   i2core.dbo.PracPracGrp ppg
JOIN   #ActivePrac            ap ON ap.PracNum     = ppg.PracNum
JOIN   GeoMap.NetworkGroup    ng ON ng.PracGrpCode = ppg.PracGrpCode;


/* -------------------------------------------------------------------------------------
   3. NETWORK ELIGIBILITY PER PRODUCT (BENEFIT OPTION) AND PRACTICE TYPE
      This is the table that lets the call centre filter by the member's option:
      "which network providers of discipline X apply to option Y?"
   ------------------------------------------------------------------------------------- */
DROP TABLE IF EXISTS GeoMap.ProductNetworkProvider;

WITH CurrentTerm AS                                                        -- VERIFY (A3)
(
    SELECT ProdCode, MAX(BenTermAsAt) AS BenTermAsAt
    FROM   i2core.dbo.ProdBenPracTypePracGrp
    WHERE  BenTermAsAt <= @AsAt
    GROUP  BY ProdCode
)
SELECT DISTINCT
       pb.ProdCode,                 -- join to the product master for the option name
       pb.BenTermAsAt,
       pn.PracNum,
       pn.PracType,
       pn.NetworkCode,
       pn.NetworkName,
       pn.PracGrpCode,
       pn.PracGrpDescr,
       pn.CapInd,
       pn.PCPInd,
       pn.AssBlockActive,
       CAST(ISNULL(pgp.PrimNetwrkInd, 0) AS bit) AS PrimaryNetworkInd,
       CASE WHEN pgp.PracGrpCode IS NULL THEN 0 ELSE 1 END AS GroupLinkedToProduct
INTO   GeoMap.ProductNetworkProvider
FROM   GeoMap.PracticeNetwork            pn
JOIN   i2core.dbo.ProdBenPracTypePracGrp pb  ON pb.PracGrpCode = pn.PracGrpCode
                                            AND pb.PracType    = pn.PracType
JOIN   CurrentTerm                       ct  ON ct.ProdCode    = pb.ProdCode
                                            AND ct.BenTermAsAt = pb.BenTermAsAt
LEFT JOIN i2core.dbo.PracGrpProd         pgp ON pgp.PracGrpCode = pb.PracGrpCode
                                            AND pgp.ProdCode    = pb.ProdCode;

CREATE CLUSTERED INDEX IX_ProductNetworkProvider ON GeoMap.ProductNetworkProvider (ProdCode, PracNum);


/* -------------------------------------------------------------------------------------
   4. PROVIDER MASTER (one row per active practice, geocoding-ready)
   ------------------------------------------------------------------------------------- */
DROP TABLE IF EXISTS GeoMap.ProviderMaster;

WITH PracticeEmail AS
(
    SELECT x.PracNum, x.EmailAddr AS PracticeEmail
    FROM (SELECT p.PracNum, p.EmailAddr,
                 ROW_NUMBER() OVER (PARTITION BY p.PracNum ORDER BY p.EffDate DESC, p.PracEmailAsAt DESC) AS rn
          FROM   i2core.dbo.PracEmail p
          WHERE  p.EmailType = 9
            AND (p.EffTo IS NULL OR p.EffTo >= @AsAt)) x
    WHERE x.rn = 1
),
StatementEmail AS
(
    SELECT x.PracNum, x.EmailAddr AS StatementEmail
    FROM (SELECT p.PracNum, p.EmailAddr,
                 ROW_NUMBER() OVER (PARTITION BY p.PracNum ORDER BY p.EffDate DESC, p.PracEmailAsAt DESC) AS rn
          FROM   i2core.dbo.PracEmail p
          WHERE  p.EmailType = 13
            AND (p.EffTo IS NULL OR p.EffTo >= @AsAt)) x
    WHERE x.rn = 1
),
StreetAddr AS
(
    SELECT x.*
    FROM (SELECT pa.PracNum,
                 NULLIF(LTRIM(RTRIM(pa.Line1)),  '') AS Line1,
                 NULLIF(LTRIM(RTRIM(pa.Line2)),  '') AS Line2,
                 NULLIF(LTRIM(RTRIM(pa.Line3)),  '') AS Line3,
                 NULLIF(LTRIM(RTRIM(pa.Suburb)), '') AS Suburb,
                 NULLIF(LTRIM(RTRIM(pa.Town)),   '') AS Town,
                 CASE WHEN NULLIF(LTRIM(RTRIM(CAST(pa.PostCode AS varchar(10)))), '') IS NULL THEN NULL
                      ELSE RIGHT('0000' + LTRIM(RTRIM(CAST(pa.PostCode AS varchar(10)))), 4) END AS PostCode,
                 pa.CntryCode, pa.ProvinceCode,
                 ROW_NUMBER() OVER (PARTITION BY pa.PracNum ORDER BY pa.PracNum) AS rn  -- use an effective date if PracAddr has one
          FROM   i2core.dbo.PracAddr pa
          WHERE  pa.AddrType = 'S') x
    WHERE x.rn = 1
),
NetworkSummary AS
(
    SELECT d.PracNum,
           COUNT(*) AS NetworkCount,
           STRING_AGG(CAST(d.NetworkName AS varchar(max)), '; ') AS NetworkNames
    FROM  (SELECT DISTINCT PracNum, NetworkName FROM GeoMap.PracticeNetwork) d
    GROUP BY d.PracNum
),
ProductSummary AS
(
    SELECT PracNum, COUNT(DISTINCT ProdCode) AS ProductCount
    FROM   GeoMap.ProductNetworkProvider
    GROUP  BY PracNum
)
SELECT
    ap.PracNum,
    RIGHT('0000000' + CAST(CAST(ap.PracNum AS bigint) AS varchar(10)), 7) AS PracNumDisplay,
    LTRIM(RTRIM(ap.PracName))                          AS PracName,
    ap.PracType,
    t.Descr                                            AS PracTypeDescr,
    ISNULL(pc.ProviderCategory, 'Unclassified')        AS ProviderCategory,
    ap.EffDate,
    ap.EffTo,
    sa.Line1, sa.Line2, sa.Line3, sa.Suburb, sa.Town, sa.PostCode,
    pr.Descr                                           AS ProvinceDescr,
    CONCAT_WS(', ', sa.Line1, sa.Line2, sa.Line3, sa.Suburb, sa.Town, sa.PostCode)                  AS DisplayAddress,
    CONCAT_WS(', ', sa.Line1, sa.Line2, sa.Line3, sa.Suburb, sa.Town, sa.PostCode, 'South Africa')  AS GeocodeAddress,
    CASE
        WHEN sa.PracNum IS NULL                                               THEN '1 No street address'
        WHEN sa.Line1 LIKE '%P%O%Box%' OR sa.Line1 LIKE '%Private Bag%'
          OR sa.Line2 LIKE '%P%O%Box%' OR sa.Line2 LIKE '%Private Bag%'       THEN '2 Postal address in street field'
        WHEN sa.Line1 IS NULL AND sa.Line2 IS NULL                            THEN '3 No street line'
        WHEN sa.Suburb IS NULL AND sa.Town IS NULL                            THEN '4 No suburb or town'
        WHEN sa.PostCode IS NULL                                              THEN '5 No postcode'
        ELSE '0 OK'
    END                                                AS AddrQualityFlag,
    CASE WHEN ns.PracNum IS NULL THEN 0 ELSE 1 END     AS IsNetworkProvider,
    ISNULL(ns.NetworkCount, 0)                         AS NetworkCount,
    ns.NetworkNames,
    ISNULL(ps.ProductCount, 0)                         AS ProductCount,
    pe1.PracticeEmail,
    pe2.StatementEmail
    -- , <practice telephone>  -- add once the telephone table is confirmed; the call centre needs it
INTO GeoMap.ProviderMaster
FROM      #ActivePrac                 ap
JOIN      i2core.dbo.PracTypeMast     t   ON t.PracType  = ap.PracType
LEFT JOIN GeoMap.ProviderCategory     pc  ON pc.PracType = ap.PracType
LEFT JOIN StreetAddr                  sa  ON sa.PracNum  = ap.PracNum
LEFT JOIN i2core.dbo.ProvinceMast     pr  ON pr.CntryCode = sa.CntryCode AND pr.ProvinceCode = sa.ProvinceCode
LEFT JOIN NetworkSummary              ns  ON ns.PracNum  = ap.PracNum
LEFT JOIN ProductSummary              ps  ON ps.PracNum  = ap.PracNum
LEFT JOIN PracticeEmail               pe1 ON pe1.PracNum = ap.PracNum
LEFT JOIN StatementEmail              pe2 ON pe2.PracNum = ap.PracNum;

CREATE UNIQUE CLUSTERED INDEX IX_ProviderMaster ON GeoMap.ProviderMaster (PracNum);


/* -------------------------------------------------------------------------------------
   5. GEOCODE STORE AND GEOCODING QUEUE
      Geocodes are kept permanently; only new or changed addresses are re-geocoded.
   ------------------------------------------------------------------------------------- */
IF OBJECT_ID('GeoMap.PracticeGeocode') IS NULL
BEGIN
    CREATE TABLE GeoMap.PracticeGeocode
    (
        PracNum         numeric(10,0)  NOT NULL CONSTRAINT PK_PracticeGeocode PRIMARY KEY CLUSTERED,
        AddressHash     varbinary(32)  NOT NULL,
        GeocodeAddress  varchar(600)   NULL,
        Latitude        decimal(9,6)   NULL,
        Longitude       decimal(9,6)   NULL,
        MatchLevel      varchar(20)    NULL,   -- Street | Suburb | PostCode | Manual | Failed
        GeocodeSource   varchar(30)    NULL,   -- e.g. AfriGIS, Google, HERE, Manual
        GeocodeDate     datetime2(0)   NULL,
        GeoPoint        geography      NULL
    );

    CREATE SPATIAL INDEX SIX_PracticeGeocode_GeoPoint ON GeoMap.PracticeGeocode (GeoPoint);
END;

-- 5a. Geocoding queue: network providers first, then everyone else.
--     Export this, geocode, load results into GeoMap.PracticeGeocode (upsert on PracNum).
SELECT pm.PracNum,
       pm.PracNumDisplay,
       pm.PracName,
       pm.ProviderCategory,
       pm.IsNetworkProvider,
       pm.AddrQualityFlag,
       pm.GeocodeAddress,
       pm.Suburb, pm.Town, pm.PostCode, pm.ProvinceDescr,   -- for suburb / postcode fallback
       HASHBYTES('SHA2_256', pm.GeocodeAddress) AS AddressHash,
       CASE WHEN g.PracNum IS NULL THEN 'New' ELSE 'Address changed' END AS QueueReason
FROM      GeoMap.ProviderMaster  pm
LEFT JOIN GeoMap.PracticeGeocode g ON g.PracNum = pm.PracNum
WHERE pm.AddrQualityFlag <> '1 No street address'
  AND (g.PracNum IS NULL OR g.AddressHash <> HASHBYTES('SHA2_256', pm.GeocodeAddress))
ORDER BY pm.IsNetworkProvider DESC, pm.ProviderCategory, pm.PracNum;

-- 5b. After loading geocodes, build the spatial point (run after every load):
--     UPDATE GeoMap.PracticeGeocode
--     SET    GeoPoint = geography::Point(Latitude, Longitude, 4326)
--     WHERE  Latitude IS NOT NULL AND Longitude IS NOT NULL;


/* -------------------------------------------------------------------------------------
   6. DATA QUALITY CHECKS (share results with Provider Networks before go-live)
   ------------------------------------------------------------------------------------- */

-- 6a. Network providers by address quality: what can be mapped at street level?
SELECT ProviderCategory, AddrQualityFlag, COUNT(*) AS Practices
FROM   GeoMap.ProviderMaster
WHERE  IsNetworkProvider = 1
GROUP  BY ProviderCategory, AddrQualityFlag
ORDER  BY ProviderCategory, AddrQualityFlag;

-- 6b. Practices sitting in a network group whose type rule does not allow their practice type.
SELECT pn.NetworkName, pn.PracGrpCode, pn.PracGrpDescr, pn.PracType, COUNT(*) AS Practices
FROM   GeoMap.PracticeNetwork pn
WHERE  pn.PracTypeRuleCheck = 'Type not allowed'
GROUP  BY pn.NetworkName, pn.PracGrpCode, pn.PracGrpDescr, pn.PracType
ORDER  BY Practices DESC;

-- 6c. Network groups currently under an assignment block.
SELECT DISTINCT NetworkCode, NetworkName, PracGrpCode, PracGrpDescr
FROM   GeoMap.NetworkGroup
WHERE  AssBlockActive = 1;

-- 6d. Practice groups configured on a product's benefit term but with no active network link.
WITH CurrentTerm AS
(
    SELECT ProdCode, MAX(BenTermAsAt) AS BenTermAsAt
    FROM   i2core.dbo.ProdBenPracTypePracGrp
    WHERE  BenTermAsAt <= @AsAt
    GROUP  BY ProdCode
)
SELECT DISTINCT pb.ProdCode, pb.PracGrpCode, pgm.Descr AS PracGrpDescr
FROM   i2core.dbo.ProdBenPracTypePracGrp pb
JOIN   CurrentTerm ct              ON ct.ProdCode = pb.ProdCode AND ct.BenTermAsAt = pb.BenTermAsAt
JOIN   i2core.dbo.PracGrpMast pgm  ON pgm.PracGrpCode = pb.PracGrpCode
WHERE  NOT EXISTS (SELECT 1 FROM GeoMap.NetworkGroup ng WHERE ng.PracGrpCode = pb.PracGrpCode);

-- 6e. Benefit-term configuration that is not mirrored in PracGrpProd (possible config gap).
SELECT ProdCode, PracGrpCode, COUNT(DISTINCT PracNum) AS Practices
FROM   GeoMap.ProductNetworkProvider
WHERE  GroupLinkedToProduct = 0
GROUP  BY ProdCode, PracGrpCode;

-- 6f. Unclassified practice types that have network providers (complete Section 1a).
SELECT pm.PracType, pm.PracTypeDescr, COUNT(*) AS NetworkPractices
FROM   GeoMap.ProviderMaster pm
WHERE  pm.ProviderCategory = 'Unclassified' AND pm.IsNetworkProvider = 1
GROUP  BY pm.PracType, pm.PracTypeDescr
ORDER  BY NetworkPractices DESC;

-- 6g. Headline counts: network providers per product and category.
SELECT pnp.ProdCode, pm.ProviderCategory, COUNT(DISTINCT pnp.PracNum) AS NetworkPractices
FROM   GeoMap.ProductNetworkProvider pnp
JOIN   GeoMap.ProviderMaster         pm ON pm.PracNum = pnp.PracNum
GROUP  BY pnp.ProdCode, pm.ProviderCategory
ORDER  BY pnp.ProdCode, pm.ProviderCategory;
