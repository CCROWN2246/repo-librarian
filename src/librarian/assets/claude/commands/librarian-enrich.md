---
description: The Librarian's enrichment cycle — fill knowledge GAPS by querying a live source and drafting a provisional, source-verified doc. Propose-only; every draft is provisional + carries its source + ships with a verify check.
allowed-tools: Bash, Read, Edit, Write
---
You are running the knowledge-base **enrichment cycle** — the active-analyst loop. Its contract:
**find a gap the corpus can't answer, query a LIVE source, and draft a PROVISIONAL, source-verified
doc as a proposal.** You never assert a fact you didn't just pull from a source, you never mark a
draft authoritative, and you propose-only — the human reviews and applies.

## The accuracy wall (non-negotiable — this is the whole brand)
- **Empty-source guard:** if the source query returns nothing / zero / an error, **do NOT draft.**
  A gap you couldn't fill stays an open gap — say so; never write "we have zero X" as if it were a finding.
- **Always provisional + source-carried:** every drafted doc is `status: provisional` and its proposal
  carries the exact `command` you ran and the `evidence` (the value you extracted). `librarian propose`
  will REJECT an `enrich_create` with empty evidence — that's the guard, enforced.
- **Verified-by-construction:** every drafted fact ships with a paired `add_check` so it re-verifies on
  every `librarian verify`. A provisional doc without its check is not done.

## Step 0 — the gap worklist (free; may end here)
```
librarian enrich --json
```
Read `gaps` and `sources`. **If `gaps` is empty, STOP** — report "no enrichable gaps" and do nothing.
`sources` lists the `[verify.sources]` you may query. If a gap has no plausible source among them,
skip it and say so — do not invent a source.

## Step 1 — stay on the user's branch (no branch needed)
Enrichment is propose-only: the drafted doc lives inside an `enrich_create` proposal and isn't written
until the user approves an apply. So run right where the user is; **do NOT create a separate branch.**
Uncommitted WIP is fine; leave it alone.

## Step 2 — per gap: query, then draft (only if the source answered)
For each gap you can plausibly fill:
1. Pick the right source from `sources` and run its query (the same shell command a `[verify.sources]`
   entry runs). Capture the exact command and the extracted value.
2. **Empty / zero / error?** Emit nothing for this gap. Note "source empty — gap unconfirmed" for the report.
3. **Non-empty?** Draft a short provisional doc and emit BOTH proposals with `librarian propose`
   (it fills base_sha256/id; leave them out). First the doc:
```
librarian propose <<'JSON'
{"type":"enrich_create",
 "targets":[{"path":"docs/ops/backup-coverage.md"}],
 "action":{"new_path":"docs/ops/backup-coverage.md","domain":"ops","status":"provisional",
           "frontmatter":{"id":"ops-backup-coverage","title":"Backup coverage","domain":"ops",
                          "status":"provisional","authority":"unverified","last_verified":"<today YYYY-MM-DD>",
                          "recheck":"30d","read_when":["when auditing backups"]},
           "body":"# Backup coverage\n\n_Provisional — drafted from a live source; see the paired check._\n\n<facts you extracted>\n",
           "spawns_check":"backup_coverage"},
 "rationale":"gap: no backup-coverage doc; filled from the warehouse",
 "provenance":{"source":"catalog-gap","command":"<exact query you ran>","evidence":"<extracted value>",
               "drafted_by":"librarian-enrich"}}
JSON
```
   Then the check that keeps it honest (E2):
```
librarian propose <<'JSON'
{"type":"add_check",
 "targets":[{"path":"docs/ops/backup-coverage.md"}],
 "action":{"check_id":"backup_coverage","source":"warehouse",
           "check":{"id":"backup_coverage","source":"warehouse","kind":"track","doc":"docs/ops/backup-coverage.md",
                    "cmd":"<same query>","extract":"scalar"}},
 "rationale":"keep the enriched fact honest"}
JSON
```
Keep drafts short and factual — only what the source supports. Bound the run: do the first ~5 gaps and
note how many remain.

## Step 3 — review IN CHAT, apply on approval (no commit)
`_index/proposals.json` now holds the enrichment proposals. Present them **right here in the chat** — per
gap: the source + command + extracted value, the drafted doc's id, and any gap you left unfilled (with
why — usually "source empty" or "no matching source"). Do not commit and do not create a report file;
proposals are propose-only until the user approves.

Ask the user which to apply. When they approve, run `librarian apply --only <enrich_id> <check_id>` — the
doc lands `status: provisional` (quarantined + TTL-flagged in STALENESS.md until they promote it) and its
check runs on every `librarian verify`. Tell them: promote a draft by editing `status:` to authoritative
once they've reviewed it.

## Invariants (do not violate)
- Propose-only until the user approves. Every draft is provisional, source-carried, and paired with a
  check. No authoritative drafts, no unsourced claims, no drafting when the source came back empty.
- Never hand-write a proposal `id` or `base_sha256` — always go through `librarian propose`.
- If `librarian enrich` reported no gaps, you should have stopped at Step 0.
