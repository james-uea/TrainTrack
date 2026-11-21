-- Network Rail Track Model centrelines (loaded by src/track_model.py), in British National Grid so
-- distances are in metres. from_node/to_node join links that share an endpoint (within 1 m).

CREATE TABLE track_links (
    asset_id TEXT PRIMARY KEY,
    elr TEXT NOT NULL, -- Engineer's Line Reference
    track_id TEXT,
    start_miles DOUBLE PRECISION,
    end_miles DOUBLE PRECISION,
    from_node INTEGER NOT NULL,
    to_node INTEGER NOT NULL,
    length_m DOUBLE PRECISION NOT NULL,
    geom geometry(LineString, 27700) NOT NULL
);

CREATE INDEX track_links_geom_idx ON track_links USING GIST (geom);
