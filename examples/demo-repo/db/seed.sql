-- citybikes demo database: 17 stations, 1284 rides.
-- Loaded into an in-memory sqlite db by db/query.py — no server, no files, no setup.
CREATE TABLE stations (
    station_id   INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    dock_count   INTEGER NOT NULL,
    active       INTEGER NOT NULL DEFAULT 1
    -- NOTE: no `region` column. docs/schema.md asserts this; the ops interview
    -- transcript claims otherwise (that claim is quarantined).
);

INSERT INTO stations (station_id, name, dock_count, active) VALUES
    (1,  'Harbor Square',    20, 1),
    (2,  'Union & 5th',      20, 1),
    (3,  'Museum Steps',     20, 1),
    (4,  'Old Mill Yard',    15, 1),   -- the exception that breaks "every station has 20 docks"
    (5,  'Cathedral Green',  20, 1),
    (6,  'River North',      20, 1),
    (7,  'Foundry Gate',     20, 1),
    (8,  'Twin Bridges',     20, 1),
    (9,  'Market Hall',      20, 1),
    (10, 'Observatory Hill', 20, 1),
    (11, 'Canal Street',     20, 1),
    (12, 'Pioneer Plaza',    20, 1),
    (13, 'Elm & Granite',    20, 1),
    (14, 'South Terminal',   20, 1),
    (15, 'Botanic West',     20, 1),
    (16, 'Ferry Landing',    20, 1),
    (17, 'Summit Loop',      20, 1);

CREATE TABLE rides (
    ride_id    INTEGER PRIMARY KEY,
    station_id INTEGER NOT NULL REFERENCES stations(station_id),
    month      TEXT NOT NULL              -- 'YYYY-MM'
);

-- 1284 rides spread across stations and two months.
WITH RECURSIVE seq(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM seq WHERE x < 1284)
INSERT INTO rides (ride_id, station_id, month)
SELECT x, (x % 17) + 1, CASE WHEN x % 3 = 0 THEN '2026-06' ELSE '2026-05' END FROM seq;
