-- Coordinates for TIPLOCs, for placing trains on the map. Loaded by src/tiploc_locations.py from
-- NaPTAN (stations), Network Rail BPLAN (everything else) and a hand-kept overrides file.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE tiploc_locations (
    tiploc TEXT PRIMARY KEY, -- no FK to locations: sources cover TIPLOCs Darwin hasn't sent yet
    name TEXT,
    geom geometry(Point, 4326) NOT NULL,
    easting INTEGER, -- OSGB36 / British National Grid (EPSG:27700); NULL for overrides given as lat/lon
    northing INTEGER,
    source TEXT NOT NULL CHECK (source IN ('naptan', 'bplan', 'override')),
    quality TEXT NOT NULL CHECK (quality IN ('good', 'suspect')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX tiploc_locations_geom_idx ON tiploc_locations USING GIST (geom);

COMMENT ON COLUMN tiploc_locations.quality IS
    'suspect: NaPTAN and BPLAN put this TIPLOC more than 2 km apart (one of them is wrong; NaPTAN is used)';
