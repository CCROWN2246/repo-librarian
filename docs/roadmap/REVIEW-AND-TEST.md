# repo-librarian core (Phases 0–2) — Review & HITL Testing Guide

Branch: `librarian/phase-0` · 12 feature commits (`b03c3f5..HEAD`) · 243 tests · zero runtime deps.
Nothing pushed. This guide is: (1) what to read, (2) automated gates, (3) a hands-on walkthrough that
exercises every capability, (4) a guarantees checklist, (5) known limits.

---

## Part 0 — How to run librarian from this branch

```bash
cd /mnt/c/Users/csqua/Desktop/repo-librarian
export PYTHONPATH="$PWD/src"          # or use your ~/.local/bin/librarian shim
alias lib='python3 -m librarian'      # this guide uses `lib`
lib --version                          # sanity check
```
`LIBRARIAN_TODAY=YYYY-MM-DD` freezes the clock (determinism). ruff: `~/.local/bin/ruff`.

---

## Part 1 — What to review (the map)

Read the commits in order — each is one self-contained capability:

| Commit | Delivers | Key files |
|---|---|---|
| `6724535` | proposal schema + trust-ladder config + provenance | `src/librarian/proposals.py`, `config.py`, `verify.py` |
| `1a7bae6` | `apply` + `query` + B6 vocab | `apply.py`, `cli.py` |
| `fb588ff` | B1 work-resumption nudge | `cli.py` (cmd_status), `assets/claude/librarian-prompt.sh`, `scaffold.py` |
| `e87f680` | `archive` command | `apply.py` (archive_doc), `cli.py` |
| `85bc5e1` | retirement-detection dream job | `dream.py` |
| `f596f01` | `why` (provenance query) | `cli.py` |
| `0b0889f` | `propose` — dream emits proposals | `proposals.py` (build_from_partial), `assets/.../librarian-dream.md` |
| `13b853c` | B4 trust-ladder auto-apply | `cli.py` (cmd_apply) |
| `a68a223` | B5 enrichment + E2 auto-checks | `enrich.py`, `catalog.py`, `assets/.../librarian-enrich.md` |

**The two spines to scrutinize hardest** (compatibility surfaces — get them right now):
- `proposals.py` — the schema. Check: the id-hash excludes `base_sha256`/`rationale`/`provenance`
  (so re-drafts dedupe — `compute_id` + `_action_signature`); `cap_tier`/`effective_tier` (the accuracy
  wall); `_validate_type_specifics` (the empty-source guard).
- `apply.py` — `_apply_fix` truth-table + `stale_targets` (the staleness guard) + `archive_doc`.

**Also worth a careful read:** the two rewritten agent prompts — `assets/claude/commands/librarian-dream.md`
and `librarian-enrich.md` — since those drive the LLM half and encode the propose-only + empty-source
invariants in prose.

---

## Part 2 — Automated gates (run first; should be green)

```bash
python3 -m unittest discover -s tests          # expect: Ran 243 tests ... OK
~/.local/bin/ruff check src tests              # expect: All checks passed!
~/.local/bin/ruff format --check src tests     # expect: N files already formatted
```

---

## Part 3 — Hands-on walkthrough (a throwaway repo)

Every scenario is copy-paste. Set up once:

```bash
export PYTHONPATH="/mnt/c/Users/csqua/Desktop/repo-librarian/src"
alias lib='python3 -m librarian'
export LIBRARIAN_TODAY=2026-07-08
T=$(mktemp -d); cd "$T"; git init -q
lib init >/dev/null            # scaffolds .librarian.toml, _index/, .claude/ glue, hooks
ls _index .claude/commands .claude/hooks
printf 'schema_version = 1\n' > .librarian.toml   # reset to a MINIMAL config for the walkthrough*
```
✓ Check: `.claude/commands/` has `librarian.md`, `librarian-dream.md`, `librarian-enrich.md`;
`.claude/hooks/` has `librarian-session.sh` + `librarian-prompt.sh`; `.claude/settings.json` wires
**both** SessionStart and UserPromptSubmit.

> *`init` writes a fully-commented config containing every section header (`[automation]`, `[enrich]`,
> `[hooks]`, …). We reset to a one-line minimal config so the scenarios below can write exactly the
> config they need — appending a second `[automation]` header to the scaffolded file is a TOML
> duplicate-table error, so each config-touching scenario rewrites the whole file with `cat >`.

### A. Catalog + query (the token-flip primitive, E1a)
```bash
mkdir -p docs
cat > docs/schema.md <<'EOF'
---
id: schema
title: Warehouse schema
domain: data
status: authoritative
last_verified: 2026-07-01
recheck: 90d
read_when: [schema questions, column names]
tags: [warehouse]
---
# Schema
The stations table has 17 active rows.
EOF
lib index
lib query --domain data --json          # structured pointers, NOT bodies
lib query schema column --json          # phrase filter (all terms present)
```
✓ Check: `query` returns id/path/status/**last_verified**/stale — pointers + freshness, never the doc
body. Empty match → exit 1.

### B. verify → provenance → why (E3)
```bash
cat > .librarian.toml <<'EOF'
schema_version = 1
[[verify.checks]]
id = "active_stations"
kind = "assert"
doc = "docs/schema.md"
cmd = "echo 17"
expect = "17"
EOF
lib verify                              # PASS
cat _index/provenance.json             # committed provenance chain
lib why stations --json                 # command + source + value + when + backing doc
```
✓ Check: `provenance.json` records `command`/`source`/`live`/`status`/`verified_at`; `why` surfaces it.
Now make it drift and confirm it's caught:
```bash
sed -i 's/echo 17/echo 15/' .librarian.toml
lib verify ; echo "exit=$?"            # DRIFT, exit 1 — a stale number becomes a red line
printf 'schema_version = 1\n' > .librarian.toml   # reset to minimal for the next scenarios
```

### C. Maintenance loop: conflict → dream → propose → apply (B2, idempotency, staleness)
```bash
# plant a contradiction marker + a wrong line
cat > docs/schema.md <<'EOF'
---
id: schema
title: Warehouse schema
domain: data
status: authoritative
last_verified: 2026-07-01
recheck: 90d
read_when: [schema questions]
tags: [warehouse]
---
<!-- KB-CONTRADICTED: verified says 17 -->
The stations table has 20 active rows.
EOF
lib index
lib dream --json | python3 -m json.tool | head -20    # open_conflicts non-empty, due=true
```
Now play the dream agent's producer step by hand (this is what `/librarian-dream` automates):
```bash
lib propose --approved <<'JSON'
{"type":"fix","targets":[{"path":"docs/schema.md","line":11}],
 "action":{"replace":{"old":"has 20 active","new":"has 17 active"},"drop_marker":true},
 "rationale":"verified source says 17"}
JSON
cat _index/proposals.json              # note base_sha256 + id were auto-filled by the CLI
lib apply --all --json | python3 -m json.tool
grep -n "active rows\|KB-CONTRADICTED" docs/schema.md
```
✓ Check: line now reads "17 active", the marker is gone, `applied:1`, `marked_done:true`
(worklist emptied → nudge reset).
**Idempotency** — re-propose + re-apply changes nothing:
```bash
lib propose --approved <<'JSON'
{"type":"fix","targets":[{"path":"docs/schema.md","line":11}],
 "action":{"replace":{"old":"has 20 active","new":"has 17 active"}},"rationale":"x"}
JSON
lib apply --all --json | python3 -c 'import sys,json; print("result:", json.load(sys.stdin)["outcomes"][0]["result"])'
```
✓ Check: `noop` (old text absent, new present → idempotent). Run-twice = zero diff.
**Staleness guard** — a proposal refuses if the file changed since it was drafted:
```bash
lib propose <<'JSON'
{"type":"fix","targets":[{"path":"docs/schema.md","line":11}],
 "action":{"replace":{"old":"17 active","new":"18 active"}},"rationale":"x"}
JSON
echo "  (someone edits the file after the draft)" >> docs/schema.md
lib apply --all --json | python3 -c 'import sys,json; d=json.load(sys.stdin); print([o["result"] for o in d["outcomes"]])'
```
✓ Check: `stale` — apply refuses the patch and tells you to re-dream. File not clobbered.

### D. archive + retirement detection (B3)
```bash
cat > docs/old-plan.md <<'EOF'
---
id: old-plan
title: Q1 migration plan
domain: data
status: shipped
last_verified: 2026-07-01
recheck: 90d
read_when: [the q1 migration]
tags: []
---
# Q1 migration — done
EOF
lib index
lib dream --json | python3 -c 'import sys,json; print("retirement:", json.load(sys.stdin)["worklist"]["retirement_candidates"])'
lib archive docs/old-plan.md --json | python3 -m json.tool
ls _archive/ ; lib index
```
✓ Check: dream flags `old-plan` as a retirement candidate (terminal status `shipped`, still in the tree);
`archive` moves it to `_archive/`, flips status→archived, reindexes; it leaves the catalog. Reversible.

### E. Enrichment loop + the empty-source guard (B5/E2 — the accuracy centerpiece)
```bash
mkdir -p etl && echo "print('etl')" > etl/run.py    # an uncovered .py file = a gap
lib index
lib enrich --json | python3 -m json.tool     # gap worklist + available sources
```
Play the enrich agent: draft **with** source evidence (accepted) …
```bash
mkdir -p docs/ops
lib propose <<'JSON'
{"type":"enrich_create","targets":[{"path":"docs/ops/pipeline.md"}],
 "action":{"new_path":"docs/ops/pipeline.md","status":"provisional",
           "frontmatter":{"id":"ops-pipeline","title":"Pipeline","domain":"ops","status":"provisional","authority":"unverified","last_verified":"2026-07-08","recheck":"30d"},
           "body":"# Pipeline\n\n_Provisional._ 1 pipeline script.\n"},
 "provenance":{"source":"repo","command":"ls pipeline.py","evidence":"pipeline.py","drafted_by":"librarian-enrich"}}
JSON
```
✓ Check: accepted. Now try to draft **without** evidence (the empty-source guard, R1):
```bash
lib propose <<'JSON'
{"type":"enrich_create","targets":[{"path":"docs/ops/empty.md"}],
 "action":{"new_path":"docs/ops/empty.md","body":"we have zero pipelines"},
 "provenance":{"source":"repo","command":"echo"}}
JSON
echo "exit=$?"
```
✓ Check: **rejected, exit 2** — "enrich_create requires non-empty provenance.evidence … never draft (R1)".
A source that returned nothing can never justify a draft. This is enforced in the schema, not just prose.
**Quarantine**: apply the good draft, then confirm provisional docs are flagged, and past-TTL ones louder:
```bash
lib apply --all --json >/dev/null
LIBRARIAN_TODAY=2026-09-01 lib index      # ~55 days later, past the 30-day default TTL
grep pipeline _index/STALENESS.md
```
✓ Check: the provisional doc shows `status=provisional; un-audited enrichment 55d (> TTL 30d)`.

### F. Trust-ladder (B4) — default-off is a real no-op; opt-in works; caps hold
```bash
lib propose <<'JSON'
{"type":"set_read_when","targets":[{"path":"docs/schema.md"}],
 "action":{"read_when":["when writing a warehouse query"]},"rationale":"routing"}
JSON
lib apply --auto --json | python3 -c 'import sys,json; print("applied:", json.load(sys.stdin)["applied"])'   # 0 — everything off
printf 'schema_version = 1\n[automation]\nset_read_when = "commit"\n' > .librarian.toml   # rewrite whole file
lib apply --auto --json | python3 -c 'import sys,json; d=json.load(sys.stdin); print("applied:",d["applied"],"committed:",d["committed"])'
```
✓ Check: default → `applied:0` (safe no-op). After opting `set_read_when` into `commit` → it auto-applies.
Now prove the accuracy wall — opt a `fix` into `commit` and confirm it still won't commit:
```bash
printf 'schema_version = 1\n[automation]\nfix = "commit"\n' > .librarian.toml
# (re-propose a fix first if none pending) then:
lib apply --auto --json | python3 -c 'import sys,json; d=json.load(sys.stdin); print("applied:",d["applied"],"committed:",d["committed"])'
```
✓ Check: `committed:False` — a `fix` is an irreversible text edit, capped at `branch` by `cap_tier`;
config can't lift it to `commit`. That's the accuracy wall.

### G. Work-resumption nudge (B1) — throttle + fast-path
```bash
lib status --hook --throttle              # first prompt of a block: nudges (if anything needs attention)
lib status --hook --throttle              # immediately after: silent (within the work-block)
# simulate resuming work hours later:
echo $(( $(date +%s) - 20000 )) > _index/.last_nudge
lib status --hook --throttle              # nudges again (work resumed)
```
✓ Check: silent within the window, re-nudges after an idle gap. The fast-path early-exits **before**
loading `catalog.json` (that's the <10ms hook guarantee).

Cleanup: `rm -rf "$T"`.

---

## Part 4 — Review checklist (the guarantees that define the brand)

- [ ] **Zero runtime deps** — `grep -A3 'dependencies' pyproject.toml` shows nothing under
      `[project.dependencies]`. stdlib only (uses `tomllib`, py≥3.11).
- [ ] **R1 hallucination guard** — enrich_create rejected without non-empty source evidence (Scenario E).
- [ ] **R2 wrong-tier** — `[automation]` default off everywhere; strict config validation (bad tier/type
      = exit 2). `apply --auto` is a no-op out of the box.
- [ ] **R3 retirement false-positive** — retirement is propose-only + positive-evidence (terminal status);
      archive is a reversible move, never a delete.
- [ ] **R4 nudge fatigue** — throttled to once per work-block; only fires when actionable.
- [ ] **R5 MCP staleness** — every `query`/`why` answer carries `last_verified` + `stale` (deferred MCP
      wraps these).
- [ ] **R6 schema churn** — `proposals.json` is `schema_version 1`, id-hash stable across re-drafts.
- [ ] **Accuracy wall** — `cap_tier` hard-caps generative/irreversible/archive at branch; main never
      reachable by tier alone.
- [ ] **Determinism** — run any command twice with the same `LIBRARIAN_TODAY` → identical output; all
      JSON state is `sort_keys=True`.
- [ ] **Exit codes** — 0 clean / 1 findings / 2 usage-or-config error, uniformly.

---

## Part 5 — Known limits / deferred (so nothing surprises you)

- **Phase 3 not built** — MCP server + PR bot (see `docs/roadmap/PHASE-3-TODO.md`). Decisions locked
  (hand-rolled stdlib MCP; `gh`-CLI manual PR bot).
- **Demo golden** not yet regenerated to include `provenance.json` (a deliberate golden-regen step).
- **`merge` apply** archives the redundant doc; folding the canonical's content is the dream agent's
  drafting step (on-branch), by design — apply doesn't merge prose.
- **`base_sha256` is whole-file** (v1): any edit to a target file makes its proposal stale (re-dream).
  Region-level hashing was deliberately deferred.
- **PR-bot round-trip** (checkbox → apply) is a Phase-3 follow-up; v1 renders the checklist as the
  human's apply worklist.
