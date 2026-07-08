---
description: The Librarian's dream cycle — draft maintenance PROPOSALS (conflicts, merges, routing, retirement) as machine-applyable objects on a branch. Propose-only; never touches main.
allowed-tools: Bash, Read, Edit, Write
---
You are running the knowledge-base **dream cycle**. Its whole contract is: **propose, never
apply.** You emit structured *proposal objects* onto a throwaway branch (plus a human-readable
`MORNING-REPORT.md`); the human reviews, approves, and runs `librarian apply`. You must not edit any
knowledge doc on the main branch, you must not apply your own proposals, and you must not delete anything.

## Step 0 — deterministic gate (free; may end here)
Run from the repo root:

```
librarian dream --json
```

Read the JSON. **If `due` is `false`, STOP immediately** — report the one-line `reason` and do
nothing else (no branch, no tokens spent on analysis). Most runs end here; that is success, not
failure.

If `due` is `true`, the `worklist` has five buckets. Note the counts; you'll work only the
non-empty ones.

## Step 1 — isolate on a branch
```
git switch -c librarian/dream-$(date +%Y%m%d) 2>/dev/null || git switch -c librarian/dream-$(date +%Y%m%d)-2
```
If the repo isn't clean, stash or abort with a note — never mix the user's WIP into a dream branch.
Everything below happens on this branch. **Do not touch files on main.**

## Step 2 — judge each non-empty bucket, and emit a proposal per decision

For every decision you make, emit a **proposal object** with `librarian propose` (it reads JSON on
stdin, hashes the target file for its staleness guard, computes the id, and appends to
`_index/proposals.json`). You supply the judgment; the CLI supplies the determinism. **Omit
`base_sha256` and `id` — never hand-compute them.** Leave proposals un-approved; the human approves.

**A. OPEN conflicts** (`worklist.open_conflicts`) — each is a quarantined `KB-CONTRADICTED` line.
Open the doc at that line and the *verified source* the marker cites, then emit exactly one of:
```
librarian propose <<'JSON'
{"type":"fix","targets":[{"path":"docs/schema.md","line":34}],
 "action":{"replace":{"old":"<exact current wrong text>","new":"<corrected text>"},"drop_marker":true},
 "rationale":"min dock count is 15, not 20",
 "provenance":{"source":"worklist:open_conflicts","drafted_by":"librarian-dream"}}
JSON
```
  - Contradiction worth keeping verbatim (e.g. a transcript)? Use `{"type":"ack","targets":[{"path":"…","line":34}],"action":{"mark":"KB-ACK"}}`.
  - Whole doc obsolete? Use an `archive` proposal (shape in D).

**B. Merge candidates** (`worklist.merge_candidates`) — same-domain pairs that *look* similar. Read
both; if genuinely redundant, first fold the redundant doc's unique content into the canonical one
(edit it on this branch), then emit:
```
librarian propose <<'JSON'
{"type":"merge","targets":[{"path":"docs/a.md"},{"path":"docs/b.md"}],
 "action":{"canonical":"docs/a.md","redundant":"docs/b.md","carry_over":["Section X — unique"],"then_archive":true},
 "rationale":"near-duplicate; folded b's unique section into a"}
JSON
```
If it's a false positive from shared vocabulary, say so in one line and emit nothing.

**C. Routing + absence audit** (`worklist.read_when_todos`, `worklist.absence_claims`):
  - Routing TODO → propose 2–4 concrete task phrases (the questions a teammate has in mind when this
    doc is the right one to open — tasks, not keywords):
    `librarian propose <<<'{"type":"set_read_when","targets":[{"path":"docs/x.md"}],"action":{"read_when":["when …","before …"]},"rationale":"empty routing"}'`
  - Absence-claim → positively check the catalog + grep. If the KB fills the gap elsewhere, emit
    `{"type":"resolve_absence","targets":[{"path":"docs/x.md","line":4}],"action":{"verdict":"stale_claim","filled_by":"docs/y.md"}}`
    (then usually a paired `fix` that edits the claim). If the gap is real, emit
    `{"type":"resolve_absence",…,"action":{"verdict":"confirmed_gap"}}` — informational; it's a candidate for enrichment later.

**D. Retirement candidates** (`worklist.retirement_candidates`) — docs whose author already set a
terminal status but which still live in the docs tree. *Positive evidence, not a guess.* Confirm the
status is genuine and nothing still points to the doc as authoritative, then emit a reversible archive:
```
librarian propose <<'JSON'
{"type":"archive","targets":[{"path":"docs/old-plan.md"}],
 "action":{"to":"_archive/old-plan.md","set_status":"archived","evidence_kind":"shipped_handoff","evidence_ref":"commit abc123"},
 "rationale":"plan shipped in HEAD"}
JSON
```
If a live doc still depends on it, say so and emit nothing.

Keep it bounded: if a bucket is very large, do the first ~10 and note how many remain.

## Step 3 — write the morning report + commit the branch
`_index/proposals.json` is now the machine-applyable artifact. Write `MORNING-REPORT.md` at the repo
root as the human-readable companion: a summary line of counts, one section per job type, and for each
proposal its file, your recommendation, and its `id` (from `librarian dream`/`propose` output). End
with a "How to apply" note:

> Review each proposal. Approve the ones you agree with and run `librarian apply --only <id> <id>…`
> (or set `"approved": true` on them in `_index/proposals.json` and `librarian apply --all`). `apply`
> re-checks each file's staleness guard, applies idempotently, reindexes, and clears the dream nudge
> when the worklist is empty.

Commit the proposals and the report to the branch:
```
git add _index/proposals.json MORNING-REPORT.md && git commit -m "chore(librarian): dream-cycle proposals $(date +%Y-%m-%d)"
```

## Step 4 — reset the nudge, report honestly
Return to the user's branch (`git switch -`), then:
```
librarian dream --mark-done
```
Tell the user, in a few lines: which branch the proposals + report are on, the count of proposals per
type, and the single highest-value item to look at first. If a bucket was empty or every merge
candidate was a false positive, **say so plainly** — do not manufacture work. Never report
"maintained" when the honest outcome was "nothing needed doing."

## Invariants (do not violate)
- Propose-only. You emit proposal objects and edit only the canonical doc of a merge (to fold content
  in). No `librarian apply`, no deletions, no changes on main.
- One branch: proposals.json + one report. Bounded work. Honest, specific reporting.
- Never hand-write a proposal `id` or `base_sha256` — always go through `librarian propose`.
- If `librarian dream` said not due, you should have stopped at Step 0.
