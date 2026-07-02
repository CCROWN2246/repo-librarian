---
id: schema
title: Database schema notes
domain: data
status: authoritative
authority: verified
last_verified: 2026-06-28
recheck: 30d
read_when: [write a query, check a column, table shapes]
owner: demo
tags: [schema, sql]
---
# Database schema notes

Two tables, seeded by `db/seed.sql`.

## stations
One row per dock station. **There is no `region` column** — regional grouping was
planned and dropped; anything claiming otherwise predates the launch cut
(verify check: `stations_no_region_column`).

- `station_id`, `name`, `dock_count`, `active`
- **17 active stations** (verify check: `active_station_count`)
- Every station has 20 docks (verify check: `min_dock_count_is_20`)

## rides
One row per ride: `ride_id`, `station_id`, `month` (`YYYY-MM` string — group by it
directly, don't parse dates).
