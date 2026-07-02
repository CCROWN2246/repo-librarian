# Conflict resolution — a worked example

The rule: **resolve by authority, never by recency.** The newest statement is not the
truest; the best-grounded one is. And never silently delete — quarantine in place, so
context survives while the falsehood stops circulating as fact.

This walkthrough mirrors a real case from the project this tool came from, reproduced
in miniature in `examples/demo-repo/`.

## The setup

A legacy lineage doc — written early, by someone without database access — asserted
two "gotchas":

1. "month partitions are NOT zero-padded" (so `month='6'`, not `'06'`)
2. "`requested_at` is ~90% NULL — don't rely on it"

Both sounded plausible. Both were **false** (the live check showed 35,215 of 35,215
rows populated in the current month). Anyone querying off those claims would write
wrong filters and discard a usable column.

## Step 1 — the intake conflict-check catches it

During intake the doc's claims were scanned against verified facts (`librarian verify`
checks + `authority: verified` docs). Two contradictions, both from a lower-authority
source (`unverified`) against live-verified facts. Lower authority loses.

## Step 2 — quarantine in place

Each false line gets wrapped, the doc's frontmatter gets `has_disputed_claims: true`,
and the doc stays whole:

```markdown
Months are not zero-padded, filter with month='6'. <!-- KB-CONTRADICTED: conflicts with [verified: partitions are zero-padded 01-12, check month_partition_zero_padded]; retained for context, not fact -->
```

`librarian index` now lists it under **OPEN conflicts** in STALENESS.md, and the
session hook nudges until it's resolved. Surfacing to the user is part of the
protocol — quarantine is containment, not resolution.

## Step 3 — add tripwire checks

The falsehoods became permanent `assert` checks (zero-padding, NULL-rate). Now a stale
doc can never re-assert them: the claim would DRIFT against the check the moment
anyone re-verified. This is the difference between correcting an error and
*immunizing* against it.

## Step 4 — resolve, one of three ways

| Option | When | How |
|---|---|---|
| **Fix** (preferred) | The doc is meant to be current | correct/remove the line, delete the marker. The repo is the source of truth; uploads are copies — fix beats hoarding stale tags. |
| **Acknowledge** | The contradiction is intentionally kept (e.g. a transcript must stay verbatim) | add `KB-ACK` inside the marker — drops off the OPEN list, still counted as acknowledged |
| **Archive** | The whole doc is obsolete | set `status: archived`, move to `_archive/` — out of the catalog, still in history |

In the real case: the lineage doc was eventually archived whole (superseded by the
schema reference), carrying its quarantine markers with it as a record.

## Scope note

Reserve `KB-CONTRADICTED` for a claim that is **false-and-misleading-now** in a doc
meant to be current. A clearly historical doc doesn't need per-line tags — mark it
`status: reference` (or archive it) at the doc level.

## See it live

```console
$ cd examples/demo-repo
$ librarian index && sed -n '/OPEN conflicts/,+5p' _index/STALENESS.md
```

The ops interview claims a `region` column exists (OPEN), and "about a dozen
stations" (acknowledged with `KB-ACK` — kept verbatim because transcripts aren't
edited); the verified station count is 17, enforced by `active_station_count`.
