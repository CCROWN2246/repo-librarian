---
id: etl-notes
title: ETL notes — ride export pipeline
domain: data
status: provisional
authority: curated
last_verified: 2026-06-25
recheck: 30d
read_when: [touch the etl, why rides lag, export cadence]
owner: demo
tags: [etl]
---
# ETL notes — ride export pipeline

**Provisional** — the vendor hasn't confirmed the dedup rule yet, so ride counts may
be revised. Anything built on `rides` inherits this status until it's settled
(provisional propagates downstream).

- Exports land weekly, Mondays.
- The `month` column is stamped at export time, not ride time — a ride on the 31st
  can land in the next month's file.
