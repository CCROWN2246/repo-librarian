---
description: The Librarian's dream cycle — draft maintenance PROPOSALS (conflicts, merges, routing, retirement) as machine-applyable objects you review in the chat. Propose-only.
allowed-tools: Bash, Read, Edit, Write
---
You are running the knowledge-base **dream cycle**. Its whole contract is: **propose, never
apply.** You emit structured *proposal objects* (`_index/proposals.json`), present them to the user right
here in the chat, and only apply the ones they approve. You must not apply your own proposals, edit a
knowledge doc, or delete anything until the user picks what to apply.

## Step 0 — deterministic gate (free; may end here)
Run from the repo root:

```
librarian dream --json
```

Read the JSON. **If `due` is `false`, STOP immediately** — report the one-line `reason` and do
nothing else (no branch, no tokens spent on analysis). Most runs end here; that is success, not
failure.

If `due` is `true`, the `worklist` has five actionable buckets (below) plus an advisory `coverage_gaps`
list. Note the counts; you'll work only the non-empty ones.

## Step 1 — stay on the user's branch (no branch needed)
Dreaming does not change any knowledge doc — it only writes proposal objects to `_index/proposals.json`.
So run it right where the user is; you will not touch their docs until they approve an apply. **Do NOT
create a separate dream branch** — that just forces the user to git-dance to review. Uncommitted WIP is
fine; leave it alone.

## Step 2 — judge each non-empty bucket, and emit a proposal per decision

For every decision you make, emit a **proposal object** with `librarian propose` (it reads JSON on
stdin, hashes the target file for its staleness guard, computes the id, and appends to
`_index/proposals.json`). You supply the judgment; the CLI supplies the determinism. **Omit
`base_sha256` and `id` — never hand-compute them.** Leave proposals un-approved; the human approves.

**A. OPEN conflicts** (`worklist.open_conflicts`) — each is a quarantined `librarian:disputed` line.
Open the doc at that line and the *verified source* the marker cites, then emit exactly one of:
```
librarian propose <<'JSON'
{"type":"fix","targets":[{"path":"docs/schema.md","line":34}],
 "action":{"replace":{"old":"<exact current wrong text>","new":"<corrected text>"},"drop_marker":true},
 "rationale":"min dock count is 15, not 20",
 "provenance":{"source":"worklist:open_conflicts","drafted_by":"librarian-dream"}}
JSON
```
  - Contradiction worth keeping verbatim (e.g. a transcript)? Use `{"type":"ack","targets":[{"path":"…","line":34}],"action":{"mark":"librarian:ack"}}`.
  - Whole doc obsolete? Use an `archive` proposal (shape in D).

**B. Merge candidates** (`worklist.merge_candidates`) — same-domain pairs that *look* similar. Read
both; if genuinely redundant, note the unique content to carry over in `carry_over` and emit the
proposal. **Do NOT edit the canonical doc yet** — the fold happens at apply time (Step 4), on the user's
branch, only if they approve:
```
librarian propose <<'JSON'
{"type":"merge","targets":[{"path":"docs/a.md"},{"path":"docs/b.md"}],
 "action":{"canonical":"docs/a.md","redundant":"docs/b.md","carry_over":["Section X — unique"],"then_archive":true},
 "rationale":"near-duplicate; carry b's unique section into a"}
JSON
```
If it's a false positive from shared vocabulary, say so in one line and emit nothing.

**C. Routing + absence audit** (`worklist.read_when_todos`, `worklist.absence_claims`):
  - Routing TODO → propose 2–4 concrete task phrases (the questions a teammate has in mind when this
    doc is the right one to open — tasks, not keywords):
    `librarian propose <<<'{"type":"set_read_when","targets":[{"path":"docs/x.md"}],"action":{"read_when":["when …","before …"]},"rationale":"empty routing"}'`
  - Absence-claim → positively check the catalog + grep. If the catalog fills the gap elsewhere, emit
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

**E. Coverage gaps** (`worklist.coverage_gaps`) — docs asserting a checkable number/count/ID with NO
verify check guarding it (so it can silently drift from its source). For each that's genuinely worth
guarding, pick a source from `[verify.sources]` and draft the check with an `add_check` proposal:
```
librarian propose <<'JSON'
{"type":"add_check","targets":[{"path":"docs/data/warehouse-schema.md"}],
 "action":{"check_id":"customers_column_count","source":"warehouse",
           "check":{"id":"customers_column_count","source":"warehouse","kind":"assert","doc":"docs/data/warehouse-schema.md",
                    "cmd":"<query that returns the number>","extract":"scalar","expect":"9"}},
 "rationale":"guard the '9 columns' claim against the warehouse"}
JSON
```
Skip a gap if the number isn't really a durable fact (a casual figure, an example) or no source fits —
say so briefly. This bucket is advisory and does NOT drive the nudge; work it opportunistically while
you're already dreaming.

Keep it bounded: if a bucket is very large, do the first ~10 and note how many remain.

## Step 3 — do NOT commit (propose-only)
`_index/proposals.json` is the machine-applyable artifact; the chat (Step 4) is the review channel. Do
not commit anything and do not create a report file on the user's branch — proposals are propose-only
until the user approves. When they later approve and apply, the fixes land in their normal working tree,
and `_index/proposals.json` + `_index/apply-log.jsonl` are the record they commit with their next commit —
no throwaway branch needed.

## Step 4 — review IN CHAT, apply on approval, reset the nudge
Present the proposals to the user **right here in the chat** — highest-value first, each in one or two
lines: what it changes, in which file, and why (use the `id` from `librarian propose` output). The user
never opens a file or touches git to review. Ask them to just say which to apply ("apply the deploy fix
and the routing one").

When they approve, run `librarian apply --only <id> <id>…` — it applies on their current branch,
re-checks each staleness guard, applies idempotently, reindexes, and clears the nudge. For a **merge**
they approved, first fold the `carry_over` content into the canonical doc, then apply (which archives the
redundant one). Finish with:
```
librarian dream --mark-done
```
If a bucket was empty or every merge candidate was a false positive, **say so plainly** — do not
manufacture work. Never report "maintained" when the honest outcome was "nothing needed doing."

## Invariants (do not violate)
- Propose-only until the user approves. You emit proposal objects; you do not run `librarian apply`, edit
  a doc, or delete anything until the user picks what to apply in the chat.
- Review happens in the chat; apply happens on the user's current branch. Never make them switch branches
  or touch git to review. No separate dream branch.
- Never hand-write a proposal `id` or `base_sha256` — always go through `librarian propose`.
- If `librarian dream` said not due, you should have stopped at Step 0.
