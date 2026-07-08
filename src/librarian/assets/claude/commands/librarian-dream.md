---
description: The Librarian's dream cycle — draft maintenance proposals (conflicts, merges, routing) on a branch. Propose-only; never touches main.
allowed-tools: Bash, Read, Edit, Write
---
You are running the knowledge-base **dream cycle**. Its whole contract is: **propose, never
apply.** You draft recommendations onto a throwaway branch and a `MORNING-REPORT.md`; the human
reviews and decides. You must not edit any knowledge doc on the main branch, and you must not
delete anything.

## Step 0 — deterministic gate (free; may end here)
Run from the repo root:

```
librarian dream --json
```

Read the JSON. **If `due` is `false`, STOP immediately** — report the one-line `reason` and do
nothing else (no branch, no tokens spent on analysis). Most runs end here; that is success, not
failure.

If `due` is `true`, the `worklist` has four buckets. Note the counts; you'll work only the
non-empty ones.

## Step 1 — isolate on a branch
```
git switch -c librarian/dream-$(date +%Y%m%d) 2>/dev/null || git switch -c librarian/dream-$(date +%Y%m%d)-2
```
If the repo isn't clean, stash or abort with a note — never mix the user's WIP into a dream branch.
Everything below happens on this branch. **Do not touch files on main.**

## Step 2 — the three judgment jobs (only for non-empty buckets)

**A. OPEN conflicts** (`worklist.open_conflicts`) — each is a quarantined `KB-CONTRADICTED` line.
For each: open the doc at that line, and open the *verified source* the marker cites. Judge and
recommend exactly one resolution, with a one-line rationale:
  - **Fix** — the line is simply wrong: give the corrected text (and note the marker should be deleted).
  - **KB-ACK** — the contradiction is worth keeping verbatim (e.g. a transcript): recommend adding `KB-ACK`.
  - **Archive** — the whole doc is obsolete: recommend `status: archived` + move to the archive dir.
Do NOT apply the edit. Write the recommendation + the exact replacement text into the report.

**B. Merge candidates** (`worklist.merge_candidates`) — same-domain doc pairs that *look* similar
by metadata. For each pair, read both docs and judge whether they are genuinely redundant. If yes:
propose which is canonical, what unique content the other holds that must survive, and a merge plan.
If no (a false positive from shared vocabulary): say so in one line and move on. This is a
pre-filter — expect real false positives.

**C. Routing + absence audit** (`worklist.read_when_todos`, `worklist.absence_claims`):
  - For each routing TODO (empty/placeholder `read_when`): read the doc and propose 2–4 concrete
    `read_when` task phrases — the questions a teammate would have in mind when this doc is the
    right one to open (not keywords; tasks). Give a ready-to-paste `read_when: [...]` line.
  - For each absence-claim ("we don't have X", "TBD", "not identified"): positively check the
    catalog + grep for X. If the KB actually fills the gap elsewhere, flag the claim as stale and
    name the doc that answers it. If the gap is real, say "confirmed gap — leave as-is."

**D. Retirement candidates** (`worklist.retirement_candidates`) — docs whose author already set a
terminal status (retired/superseded/shipped/done/…) but which still live in the docs tree. These are
*positive evidence*, not a guess. For each: open the doc, confirm the status is genuine (not a
mislabel) and that nothing still points to it as authoritative. If it's truly done, recommend
`librarian archive <path>` (reversible: status flip + git mv, never a delete). If a live doc still
depends on it, say so and leave it. **Propose only — never archive during the dream.**

Keep it bounded: if a bucket is very large, do the first ~10 and note how many remain.

## Step 3 — write the morning report
Write `MORNING-REPORT.md` at the repo root. Structure it so every item is sk-immable and
actionable: a summary line of counts, then one section per job type, each proposal with its file,
the recommendation, and exact copy-paste text. End with a "How to apply" note: review each, apply
the ones you agree with, then `librarian index` (and `librarian dream --mark-done` to clear the
nudge). Commit only the report (and any report-adjacent scratch) to the branch:

```
git add MORNING-REPORT.md && git commit -m "chore(librarian): dream-cycle proposals $(date +%Y-%m-%d)"
```

## Step 4 — reset the nudge, report honestly
Return to the user's branch (`git switch -`), then:
```
librarian dream --mark-done
```
Tell the user, in a few lines: which branch the report is on, the count of proposals per type, and
the single highest-value item to look at first. If a bucket was empty or every merge candidate was
a false positive, **say so plainly** — do not manufacture work. Never report "maintained" when the
honest outcome was "nothing needed doing."

## Invariants (do not violate)
- Propose-only. No edits to knowledge docs, no deletions, no changes on main.
- One branch, one report. Bounded work. Honest, specific reporting.
- If `librarian dream` said not due, you should have stopped at Step 0.
