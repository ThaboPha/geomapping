-- Bonitas geo-mapping: Unity Catalog setup for the Streamlit app.
-- Run in Databricks SQL as a catalog/schema owner. Replace <app-service-principal> with the
-- application ID shown on the app's page after it is created.

CREATE CATALOG IF NOT EXISTS bonitas_geo;
CREATE SCHEMA  IF NOT EXISTS bonitas_geo.geomap;

-- 1. Tables landed from SQL Server (GeoMap schema, scripts 01 and 02), same names and columns:
--      ProviderMaster, ProductNetworkProvider, PracticeGeocode, ProviderCategory, AccessStandard,
--      SpecialistHospitalAlignment, MemberAccess
--    Land them with Lakeflow Connect (SQL Server), ADF or a JDBC job.
--    Delta has no geography type: exclude PracticeGeocode.GeoPoint and MemberLocation.GeoPoint
--    when landing. The app uses Latitude/Longitude with haversine distance.

-- 2. Suburb / postcode centroids for the call centre location search.
--    Source suggestion: Stats SA sub-place centroids joined to postal codes.
CREATE TABLE IF NOT EXISTS bonitas_geo.geomap.PlaceCentroid (
  Place     STRING  COMMENT 'Suburb or sub-place name',
  Town      STRING,
  PostCode  STRING  COMMENT '4 characters, keep leading zero',
  Province  STRING,
  Geotype   STRING  COMMENT 'Metro | Urban | Rural',
  Latitude  DOUBLE,
  Longitude DOUBLE
);

-- 3. Friendly benefit option names (ProdCode from ProdBenPracTypePracGrp).
CREATE TABLE IF NOT EXISTS bonitas_geo.geomap.ProductOption (
  ProdCode   STRING,
  OptionName STRING
);

-- 4. Optional: operational member lookup for agents (approved access only).
--    Keep it narrow: no names, ID numbers or contact details.
-- CREATE OR REPLACE VIEW bonitas_geo.geomap.MemberLookup AS
-- SELECT m.MemberNumber, m.ProdCode, m.Suburb, m.Geotype, m.Latitude, m.Longitude
-- FROM   <member geocode source> m
-- WHERE  m.IsActive = 1;

-- 5. Grants for the app's service principal.
GRANT USE CATALOG ON CATALOG bonitas_geo                TO `<app-service-principal>`;
GRANT USE SCHEMA  ON SCHEMA  bonitas_geo.geomap         TO `<app-service-principal>`;
GRANT SELECT      ON SCHEMA  bonitas_geo.geomap         TO `<app-service-principal>`;
-- Also give the service principal CAN USE on the SQL warehouse (added as an app resource).
