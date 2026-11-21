-- The path a train takes between two consecutive placed stops (calls or passing points), shared by
-- every train running between them. Built by src/segment_paths.py after the timetable loads.

CREATE TABLE segment_paths (
    from_tiploc TEXT NOT NULL,
    to_tiploc TEXT NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('track', 'straight')),
    -- why a straight line: an end isn't on Network Rail track, no track connects them, or the track
    -- route is more than 3x the straight distance (probably a wrong point or a missing link)
    fallback_reason TEXT CHECK (fallback_reason IN ('off_network', 'no_path', 'detour')),
    length_m DOUBLE PRECISION NOT NULL,
    straight_m DOUBLE PRECISION NOT NULL,
    geom geometry(LineString, 4326) NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (from_tiploc, to_tiploc)
);

CREATE INDEX segment_paths_geom_idx ON segment_paths USING GIST (geom);
