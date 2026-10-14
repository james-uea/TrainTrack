CREATE TABLE cis_codes (
    code VARCHAR(4) PRIMARY KEY,
    name VARCHAR(256)
);

-- TocRefs
CREATE TABLE train_operator_codes (
    toc VARCHAR(2) PRIMARY KEY,
    name VARCHAR(256)
);

-- Location references, populated by the ref v4 schema
CREATE TABLE locations (
    tiploc VARCHAR(7) NOT NULL UNIQUE PRIMARY KEY,
    location_name VARCHAR(30) NOT NULL, -- locname
    reservation_code VARCHAR(3),  -- CRS
    train_operator_code VARCHAR(2)  -- TOC
);

CREATE TABLE vias (
    at VARCHAR(3),  -- CRS
    dest VARCHAR(7) NOT NULL REFERENCES locations(tiploc), -- tiploc rule 0
    tiploc1 VARCHAR(7) NOT NULL REFERENCES locations(tiploc), -- tiploc rule 1
    tiploc2 VARCHAR(7) REFERENCES locations(tiploc), -- tiploc rule 2 (optional)
    viatext VARCHAR(256) NOT NULL
);

CREATE TABLE late_reasons (
    code SMALLINT PRIMARY KEY,
    reason VARCHAR(256)
);

CREATE TABLE cancellation_reasons (
    code SMALLINT PRIMARY KEY,
    reason VARCHAR(256)
);

-- Train journeys / current status, initialized by the v8 schema and updated by the consumer
CREATE TABLE train_journeys (
    rid VARCHAR(16) NOT NULL PRIMARY KEY,
    train_id VARCHAR(16) NOT NULL,
    uid VARCHAR(16) NOT NULL,
    scheduled_start DATE NOT NULL,
    toc_code VARCHAR(2) NOT NULL, -- Doesn't reference toc table due to certain keys being absent from ref
    status VARCHAR(16),
    is_passenger BOOLEAN,
    cancelled BOOLEAN,
    deleted BOOLEAN,
    last_tiploc VARCHAR(7) REFERENCES locations(tiploc),
    last_report_type VARCHAR(10) CHECK (last_report_type IN ('arrival', 'departure', 'pass')),
    last_reported_at TIMESTAMPTZ,
    cancel_reason SMALLINT REFERENCES cancellation_reasons(code)
);

CREATE TABLE train_stops (
    rid VARCHAR(16) NOT NULL REFERENCES train_journeys(rid) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    tiploc VARCHAR(7) NOT NULL REFERENCES locations(tiploc),
    location_type VARCHAR(4) NOT NULL,
    activities TEXT,
    planned_activities TEXT,
    cancelled BOOLEAN NOT NULL DEFAULT FALSE,
    platform TEXT,
    public_arrival TIME,
    public_departure TIME,
    working_arrival TIME,
    working_departure TIME,
    working_pass TIME,
    actual_arrival TIME,
    actual_departure TIME,
    actual_pass TIME,
    PRIMARY KEY (rid, sequence)
)
