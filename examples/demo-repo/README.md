---
id: demo-readme
title: Citybikes demo — how to drive it
domain: reference
status: authoritative
authority: curated
last_verified: 2026-06-28
recheck: 365d
read_when: [how to run the demo, demo tour]
owner: demo
tags: [demo]
---
# Citybikes — the repo-librarian demo corpus

A tiny fake analytics project wired up the way a real information-rich repo would be.
Everything runs offline (verify queries an in-memory sqlite db). Try, from this directory:

```console
$ librarian index        # rebuild _index/ (CATALOG.md, STALENESS.md, catalog.json)
$ librarian verify       # 4 checks: one is DELIBERATELY drifting (read on)
$ librarian status       # the one-screen health summary
$ librarian search "write a query"
$ librarian ingest       # one vendor email is waiting in _inbox/
```

What's planted here, on purpose:

- **A drifting doc fact** — `docs/schema.md` says every station has 20 docks; the
  database says Old Mill Yard has 15. `librarian verify` flags `min_dock_count_is_20`
  as DRIFT and points at the doc to fix.
- **A stale baseline** — `total_rides` is tracked, and the recorded baseline (1210) is
  behind the live count, so verify reports CHANGED (not a failure — the value
  legitimately moves; accept it with `--update-baselines`).
- **A quarantined conflict + an open one** — `transcripts/ops-interview.md`
  (authority: unverified) claims "about a dozen stations" (acknowledged with KB-ACK)
  and "each station has a region code" (an OPEN conflict, listed in STALENESS.md).
- **A provisional doc** (`docs/etl-notes.md`) and **an inbox item**
  (`_inbox/vendor-email.md`) so the flagged/intake sections have something to show.
