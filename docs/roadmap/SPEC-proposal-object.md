# Spec: the proposal object (the automation spine)

Draft v1, 2026-07-08. Status: FOR REVIEW. This is a compatibility surface — once consuming repos
carry proposals, `schema_version` bumps are breaking. Get it right here.

## Why this exists

Today the dream cycle emits **prose** a human re-types by hand. The proposal object replaces that with a
**machine-applyable unit**. One schema, consumed by four surfaces:
- `librarian apply` executes it
- `librarian archive` is one type of it
- the `[automation]` trust-ladder decides which types auto-apply
- the PR bot renders it as a checkbox
And two producers emit it: `librarian-dream` (maintenance) and `librarian-enrich` (generation).

## The object

```jsonc
{
  "schema_version": "1",
  // id = sha256[:12] over ONLY: type + sorted targets[].path + the action identity signature
  //   (fix.replace.old / archive.to / merge.canonical+redundant). EXCLUDES base_sha256, rationale,
  //   provenance -> re-drafting the same logical proposal after a file edit yields the SAME id and
  //   dedupes correctly. (eng-review: id/dedup fix)
  "id": "p_<sha256[:12] of type + targets[].path + action-signature>",
  "type": "fix | ack | archive | merge | set_read_when | resolve_absence | enrich_create | add_check",
  "approved": false,          // the ONE human bit (see "Approval" below)
  "targets": [                // ARRAY: EVERY file the proposal touches carries its own staleness guard (A2)
    { "path": "docs/foo.md", "line": 34, "base_sha256": "<hash of this file at draft time>" }
    // merge/archive list BOTH files; apply refuses if ANY listed file changed since draft
  ],
  "action": { /* type-specific, see below */ },
  "rationale": "one line: why this proposal exists",
  "provenance": {
    "source": "worklist:open_conflicts | verify:warehouse | git | catalog-gap",
    "command": "psql -c 'select ...'",     // present for verify/enrich-derived
    "evidence": "extracted value / marker text / commit sha",
    "drafted_at": "2026-07-08",
    "drafted_by": "librarian-dream | librarian-enrich"
  },
  "risk": {
    "reversible": true,        // git mv + status flip = true; destructive text edit = false
    "generative": false,       // true = LLM produced net-new content -> hard-capped at branch tier
    "writes_to": "branch"      // branch | main ; main writes require explicit opt-in
  }
}
```
Dropped from v1: `anchor` (eng-review C1 — whole-file staleness makes line-drift recovery unreachable).

**Authoritative location (eng-review A4):** `proposals.json` lives at `_index/proposals.json` on exactly
ONE active dream branch at a time. A new `librarian dream` refuses to start if an un-applied dream branch
already exists (points the user at it), so there is never ambiguity about which list `apply` reads.
`MORNING-REPORT.md` is the same list rendered for humans.

## Per-type `action` payloads

```jsonc
// fix — correct a wrong line, optionally drop its KB-CONTRADICTED marker
"action": { "replace": { "old": "<exact text>", "new": "<corrected text>" }, "drop_marker": true }

// ack — keep a contradiction verbatim (transcripts): add KB-ACK to the marker
"action": { "mark": "KB-ACK" }

// archive — retire a whole doc (reversible: git mv + status flip, never delete)
"action": { "to": "_archive/old.md", "set_status": "archived",
            "evidence_kind": "merged_patch | superseded | shipped_handoff | age",
            "evidence_ref": "commit abc123 | supersedes: docs/new.md" }

// merge — fold a redundant doc into a canonical one
"action": { "canonical": "docs/a.md", "redundant": "docs/b.md",
            "carry_over": ["Section X — unique content that must survive"], "then_archive": true }

// set_read_when — fill empty/placeholder routing phrases
"action": { "read_when": ["when a teammate asks ...", "before touching ..."] }

// resolve_absence — audit a "we don't have X" claim
"action": { "verdict": "stale_claim | confirmed_gap", "filled_by": "docs/x.md" }
//   stale_claim -> proposes editing the claim; confirmed_gap -> informational, may spawn an enrich_create

// enrich_create — GENERATIVE: draft a provisional doc from a live source
"action": { "new_path": "docs/ops/backup-coverage.md", "domain": "ops", "status": "provisional",
            "frontmatter": { /* full skeleton */ }, "body": "<drafted content>",
            "spawns_check": "backup_coverage" }   // links to the add_check that will keep it honest

// add_check — register the verify check that guards an enriched fact (E2)
//   Writes a JSON check object to _index/generated-checks.json (stdlib writes JSON; NO hand-emitted
//   TOML). config.py loads .librarian.toml AND merges the sidecar. Human checks stay in TOML,
//   machine checks stay in JSON. (eng-review A3 decision)
"action": { "check_id": "backup_coverage", "source": "warehouse",
            "check": { "id": "backup_coverage", "source": "warehouse", "kind": "track",
                       "cmd": "...", "extract": "scalar" } }
```

## `librarian apply` contract

```
librarian apply [--all | --only <id>...] [--tier off|branch|commit] [--dry-run] [--json]
```
For each proposal where `approved` is true (or selected by `--only`):
1. **Staleness check:** recompute `base_sha256` for EVERY entry in `targets`. If ANY changed, mark `stale`, skip, report "re-dream". (The patch-no-longer-applies guard, now multi-file.)
2. **fix apply truth-table (eng-review C2 — encode, don't guess):**
   - `{old present, new absent}`  -> apply the replace
   - `{old absent, new present}`  -> idempotent no-op, mark `applied` (run-twice = zero diff)
   - `{old absent, new absent}`   -> refuse, mark `stale` (someone else edited it; re-dream)
   Non-text actions (archive/set_read_when/ack) are idempotent by the same principle: already-satisfied -> no-op.
3. **Apply** the typed action to the working tree.
4. **Log** to `_index/apply-log.jsonl` (id, type, targets, timestamp, result).
5. After all: **reindex once.** Then `dream --mark-done` ONLY IF the post-apply worklist is empty
   (eng-review C3 — never blanket-mark-done after a partial apply; stale/unapplied items must keep nudging).

Apply writes to the working tree and leaves the commit to the human (or to the tier, below). Never
force, never delete, never touch main implicitly.

## Provisional-doc lifecycle (eng-review — enrichment safety)

An `enrich_create` doc lands `status: provisional`. The catalog MUST quarantine provisional docs:
counted separately, never treated as authoritative in routing, and stamped with a decay TTL. A
provisional doc unreviewed past `[enrich].provisional_ttl_days` gets flagged in STALENESS.md ("un-audited
enrichment, N days old") so the engine can never quietly fill the shelves with un-promoted claims.

## Provenance persistence (eng-review A5)

`_index/provenance.json` IS committed (so `librarian why` answers after a fresh clone). Git-noise is
mitigated the way `baselines.json` already does it: `json.dumps(..., indent=2, sort_keys=True)` for a
stable, minimal-diff serialization. Revisit only if diff noise proves painful.

## Test mandate for Phase 0 (eng-review T1 — bake in, don't defer)

The proposal object is a compatibility surface, so Phase 0 ships with: a golden `proposals.json` fixture
per type; an apply **idempotency** test (apply twice, second run = zero diff); a **staleness** test
(mutate a target, assert refusal); a **multi-file staleness** test (mutate the second file of a merge,
assert refusal); a schema-version round-trip test. Determinism via `LIBRARIAN_TODAY`, same as the engine.

## Trust-ladder (`[automation]`) integration

Config maps `type -> tier`. Default for EVERY type is `off` (propose-only). Tiers:
- `off`    — propose only; human runs `apply`
- `branch` — auto-apply to the dream branch (human reviews the branch, merges)
- `commit` — auto-apply AND commit to the dream branch (still never main by default)

**Hard invariants that override config (the accuracy wall):**
- `risk.generative == true` (enrich_create) -> capped at `branch`, can never be `commit`.
- `risk.reversible == false` -> capped at `branch`.
- `writes_to == "main"` -> requires an explicit separate opt-in key, never reachable by tier alone.
- retirement/archive proposals -> `branch` max (a wrongly-archived live doc must be caught in review).

## RESOLVED DESIGN DECISIONS (2026-07-08)

1. **Approval mechanism = agent-assisted, in-chat (primary v1 path).** The dream agent presents proposals
   in the Claude session with a per-item recommendation; the human approves conversationally ("apply 1, 3,
   5"); the agent flips `approved` and runs `librarian apply`. The terminal path (`apply --only <id>`) is the
   underlying mechanism the agent calls, and stays available for CLI/CI use. PR-bot checkboxes (E4) are the
   team-scale path, layered on in Phase 3. All three write the same `approved` bit — this decides which is
   built first, not which exists.

2. **Enrichment provisional/verified split = auto-apply the check, hold the doc.** An `enrich_create` is
   generative -> provisional -> always held for human review (branch tier max). Its paired `add_check` is
   deterministic and verified-by-construction, so it may auto-apply at branch tier. The fact arrives labeled
   provisional AND already guarded by a recurring check.

3. **base_sha256 granularity = whole-file for v1.** Simpler, and a changed target doc genuinely warrants a
   re-dream. Revisit region-level hashing only if false-stale rates prove annoying at scale.
```
