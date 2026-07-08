# The dream cycle

Most of repo-librarian is deterministic and free: `index` inventories, `verify` fact-checks,
`status` flags. But four kinds of upkeep need *judgment* — and judgment costs tokens:

- **OPEN conflicts** — a `KB-CONTRADICTED` line is quarantined, but someone has to decide
  fix-vs-acknowledge-vs-archive and write the correction.
- **Duplicate docs** — two docs drift into overlapping territory; merging them is a reading-and-
  rewriting job.
- **Weak routing** — docs with empty or `TODO` `read_when` don't route; good task phrases have to
  be written.
- **Absence-claims** — a doc says "we don't have X"; someone has to check whether the KB already
  fills that gap elsewhere.

The **dream cycle** (`/librarian-dream`) does exactly these four, on your schedule, **propose-only**. It's
modeled on the good invariants of Garry Tan's gbrain "dream" — deterministic-work-before-LLM-work,
a review queue instead of auto-apply, honest reporting of no-ops — without the embeddings/DB
machinery repo-librarian deliberately avoids.

## How it works

```
librarian dream            # deterministic: build the worklist, tell you if it's DUE
librarian dream --json     # same, machine-readable — what /librarian-dream consumes
librarian dream --mark-done  # stamp the worklist reviewed; resets the nudge
```

`librarian dream` walks the catalog and builds a **worklist** of the four buckets above — for zero
tokens. The `/librarian-dream` slash command is the agent half: it reads that worklist and drafts
proposals. The split is deliberate — the CLI decides *what* needs attention deterministically; the
model only spends tokens on the judgment.

### The delta gate — why most runs cost nothing

`--mark-done` writes a content hash of the current worklist to `_index/.last_dream`. A dream is
**DUE** only when the worklist is non-empty **and** either it *changed* since you last reviewed it,
or the *same* items have sat unreviewed longer than `[dream].nudge_after_days` (default 14). So:

- Nothing new, recently reviewed → **not due**, zero cost. This is the common case.
- New conflict / new duplicate / new routing gap appears → **due**, `status` nudges you.
- You keep ignoring the same items → re-nudged after two weeks, not every session.

`librarian status` (and the session-start hook) surface the nudge — "N maintenance items ready —
run /librarian-dream" — computed cheaply from `catalog.json`, no extra filesystem walk.

## What `/librarian-dream` does (propose-only, on a branch)

1. Runs `librarian dream --json`. **If not due, it stops** — no branch, no tokens.
2. Creates `librarian/dream-<date>` and does the judgment work for each non-empty bucket:
   conflict resolutions (with exact replacement text), merge plans (canonical + what to preserve),
   `read_when` proposals, absence-claim audits, and retirement candidates (docs marked with a
   terminal status but still in the tree — propose-only archive).
3. Writes everything to `MORNING-REPORT.md` and commits **only that** to the branch. Main is never
   touched; nothing is auto-applied; nothing is deleted.
4. Runs `librarian dream --mark-done` and tells you where the report is and what to look at first.

You review the report, apply what you agree with, `librarian index`. The report *is* the review
queue — the same design gbrain settled on ("auto-accept is intentionally NOT a thing"), and doubly
right for a company KB where a wrong "fix" propagates.

## Cost & cadence

At the tool's target scale (~200–300 docs) most nights have no delta, so a strict nightly cron
would mostly pay to do nothing. Prefer the **session-start nudge** (free; fires only when due) or a
**weekly cron**. If you do schedule it headless (`claude -p`), note that as of mid-2026 programmatic
runs bill a separate metered pool rather than your interactive quota — cheap for this workload
(single dollars/month with Haiku/Sonnet and the delta gate), but not literally free.

## Config

```toml
[dream]
nudge_after_days = 14    # re-nudge on the SAME items after N days (0 disables the nudge entirely)
merge_similarity = 0.6   # metadata Jaccard (0-1) to flag a doc pair as a merge candidate
```

`merge_similarity` is a deterministic pre-filter over title + `read_when` + `tags`; expect false
positives (shared vocabulary), which `/librarian-dream` is told to identify and discard. Lower it to catch
more pairs, raise it to reduce noise.
