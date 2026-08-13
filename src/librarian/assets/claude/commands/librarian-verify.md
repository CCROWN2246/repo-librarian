---
description: Fact-check the repo's documented claims against their live sources and report any drift.
allowed-tools: Bash
---
Run the librarian's fact-checker from the repo root and give me a TIGHT, answer-first summary:

1. `librarian verify` — run every configured check (doc claims vs. their live sources).

Then report:
- **PASS / total** — how many documented facts still check out.
- **DRIFT** — for each: the doc + the value it claims → the live value. This is the list to fix NOW
  (a stale number in a doc that a live source disagrees with).
- **CHANGED** (tracked values that legitimately moved — accept with `librarian verify --update-baselines`)
  and **ERROR** (a check couldn't run) — one line each.
- **SKIP** — checks whose source isn't connected yet; not a problem, they go green when it is.

If there are **no checks configured**, say so and offer the guided wiring — do NOT send them off to
hand-write TOML:
- `librarian connect <data-dir>` — drafts a check per data file (row count + schema guard) as proposals
  they review, then `librarian apply`.
- `librarian add-check <file> --intent rows|schema` — wires ONE check; it runs the command, shows the
  live value, and asks before freezing it as the expected value.

A high-value checkable fact should have a check so it can never silently rot. (`/librarian-dream` and
`/librarian-enrich` also propose these for you.) Full guide: `docs/verify-recipes.md`.

If everything passed, say so in one line.
