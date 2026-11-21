-- Each TIPLOC's nearest point on Network Rail track, for routing between stops along the track.
-- A point far from track is 'off_network' if it's a NaPTAN station (Elizabeth line core, Tyne & Wear
-- Metro, bus stops...) and 'suspect' if it only comes from BPLAN.

ALTER TABLE tiploc_locations
    ADD COLUMN snap_link TEXT, -- track_links.asset_id (no FK: track_links is replaced on reload)
    ADD COLUMN snap_along DOUBLE PRECISION, -- metres from the start of snap_link
    ADD COLUMN snap_distance_m DOUBLE PRECISION,
    ADD COLUMN snap_geom geometry(Point, 27700),
    DROP CONSTRAINT tiploc_locations_quality_check,
    ADD CONSTRAINT tiploc_locations_quality_check CHECK (quality IN ('good', 'suspect', 'off_network'));

COMMENT ON COLUMN tiploc_locations.quality IS
    'good; off_network: a NaPTAN station more than 500 m from Network Rail track; suspect: not used, '
    'either a BPLAN point more than 500 m from track, or (before track snapping) NaPTAN and BPLAN more than 2 km apart';
