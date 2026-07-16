# Layer 3 — adversarial semantic-correctness sweep findings

_Run wf_1f8a185c-552 · 59 agents · ~4.4M subagent tokens · 12 findings → 11 deduped bugs (6 medium, 5 low). All survived 3-skeptic majority-refutation and were re-verified in synthesis._

## Summary

All 12 surviving findings were re-verified against the source and hold up as real semantic defects. After deduplication (the two ingest existing-frontmatter findings share one root cause and one fix, so they are merged) there are 11 distinct bugs: 6 medium, 5 low. The through-line is the project's own "fail loud, never swallow / guard the degenerate case" rule being violated — every bug is a case where the tool either silently drops user input, masks the exact failure mode the catalog exists to prevent (false-absence, undetected drift), performs a wrong-or-destructive edit, or misreports an audit outcome, in each case reporting success or exiting green. None require exotic input beyond a hand-authored proposal or a corrupted sidecar; several are reachable on the ordinary first-run/merge-conflict path. Ranked most-destructive first: self-referential merge silently retires the kept doc; corrupt baselines silently disables drift detection (the tool's one job) and --update-baselines then cements the drifted number; apply-fix edits the wrong (frozen) occurrence and reports success; a REFUSED merge has already mutated the canonical but logs 'refused'; ingest silently drops --read-when/--domain/--status on docs that already have frontmatter; backfill mints colliding ids with no warning. The five lows are correctness/consistency papercuts (silent query truncation with no total, deletion-fix false-STALE, intra-list carry_over dup, why --json empty stdout, backfill title lifted from a code-fence comment).

## Bugs (ranked most-destructive first)

### 1. [MEDIUM] apply (merge) — Self-referential merge (canonical == redundant) silently retires the doc it should keep, and reports success

Neither propose-time validation (_validate_type_specifics) nor _apply_merge (apply.py:314-339) guards against action.canonical == action.redundant. The carry_over fold runs on the doc, then _archive_move retires that SAME doc: it is flipped to status: archived and moved out of the live tree into _archive/, and apply returns result=applied, exit 0 — 'merged X into X; archived X -> _archive/X'. The 'kept' canonical (in the repro a T4 ground-truth doc) is effectively deleted from the corpus while the tool signals a clean successful merge. Recoverable from _archive (so not high severity), but it is a destructive edit reported as success on a degenerate input, exactly the case the 'guard-the-degenerate-case' rule targets. Ranked first because it is the only finding that removes a live doc.

**Repro:**

```bash
cd /mnt/c/Users/csqua/Desktop/repo-librarian
python3 benchmarks/gen_corpus.py --out /tmp/f3 --docs 45 --seed 1007
printf '%s' '{"type":"merge","targets":[{"path":"docs/finance/pricing-strategy.md"}],"action":{"canonical":"docs/finance/pricing-strategy.md","redundant":"docs/finance/pricing-strategy.md","carry_over":[{"target":"tags","content":["x"]}]}}' > /tmp/f3/m.json
PYTHONPATH=src python3 -m librarian.cli propose --root /tmp/f3 /tmp/f3/m.json
PYTHONPATH=src python3 -m librarian.cli apply --root /tmp/f3 --only p_380eaaf1573e   # -> [applied]
ls /tmp/f3/docs/finance/pricing-strategy.md   # GONE from live tree
ls /tmp/f3/_archive/pricing-strategy.md       # canonical silently retired
```

**Proposed regression test:** In tests/test_apply.py (MergeTests / ApplyCase): write docs/keep.md via make_doc(id='keep'); p = proposals.make('merge', [self.target('docs/keep.md')], {'canonical':'docs/keep.md','redundant':'docs/keep.md','carry_over':[{'target':'tags','content':['x']}]}); oc = self.apply(p); self.assertNotEqual(oc.result, ap.APPLIED)  # must refuse a self-merge; self.assertTrue((self.root/'docs/keep.md').exists()); self.assertFalse((self.root/'_archive/keep.md').exists()). Fix at propose validation (reject canonical==redundant) is preferable so it never reaches apply.

### 2. [MEDIUM] verify (also doctor) — Corrupt/unparseable baselines.json is swallowed to {} — drift detection silently disabled, run stays green, and --update-baselines cements the drifted value

verify.load_baselines() (verify.py:104-112) catches JSONDecodeError/OSError and returns {} — a present-but-corrupt file (e.g. git merge-conflict markers after two branches both ran verify --update-baselines, a truncated write, or a bad hand-edit) is indistinguishable from a clean first run. Every `track` check then reports NEW instead of CHANGED, the summary shows 0 CHANGED / 0 DRIFT, verify exits 0 with no warning, and doctor (same loader) prints [OK] exit 0. The known drift (open_claims_backlog baseline 87 vs live 93) is fully masked. Worse, `verify --update-baselines` on the corrupt file overwrites it with current live values, permanently discarding the recorded 87 and baking the drifted 93 in as the new baseline. This defeats the tool's headline promise ('a stale number becomes a red line in CI instead of a wrong number in a deliverable') and does so silently.

**Repro:**

```bash
cd /mnt/c/Users/csqua/Desktop/repo-librarian
python3 benchmarks/gen_corpus.py --out /tmp/l3v/corpus --docs 45 --seed 1002
PYTHONPATH=src python3 -m librarian.cli verify --root /tmp/l3v/corpus; echo EXIT=$?   # baseline: CHANGED open_claims_backlog 87->93
printf '<<<<<<< HEAD\n{}\n=======\n{}\n>>>>>>> branch\n' > /tmp/l3v/corpus/_index/baselines.json
PYTHONPATH=src python3 -m librarian.cli verify --root /tmp/l3v/corpus; echo EXIT=$?   # now 0 DRIFT / 0 CHANGED, exit 0, no warning
PYTHONPATH=src python3 -m librarian.cli doctor --root /tmp/l3v/corpus; echo EXIT=$?   # [OK], exit 0
PYTHONPATH=src python3 -m librarian.cli verify --root /tmp/l3v/corpus --update-baselines; cat /tmp/l3v/corpus/_index/baselines.json   # cements 93
```

**Proposed regression test:** New test in tests/test_verify.py: build a corpus with one `track` check and a valid baselines.json recording an OLD value; overwrite _index/baselines.json with conflict-marker text; run cli.main(['verify','--root',root]) capturing streams. Assert the run is NOT reported clean — i.e. it surfaces an error/warning mentioning 'baselines' and does not exit 0 with '0 CHANGED'. Also assert `verify --update-baselines` on the corrupt file does NOT silently overwrite it (should refuse until the corruption is resolved). Requires load_baselines to distinguish absent (return {}) from present-but-unparseable (raise/flag).

### 3. [MEDIUM] apply (fix) — apply-fix ignores target.line and replaces the FIRST occurrence — edits the wrong (frozen) line and reports 'applied'

_apply_fix (apply.py:97-98) does text.replace(old, new, 1) and never consults tgt.line. When `old` is not unique — a frozen historical value on line 13 and the actual stale value on line 15 both read '379 carriers' — a proposal that correctly sets targets[0].line=15 has its line ignored: line 13 (the frozen baseline that must not change) is rewritten to 412, line 15 (the intended target) is left stale, and apply returns result=applied '...replaced wrong text', exit 0. A corrupting, incorrect edit is reported as success. Mitigating context (why medium, not high): SPEC-proposal-object.md dropped anchor/line-drift recovery and calls `old` the 'exact text', so a well-formed proposal is expected to make `old` unique; but validation accepts a non-unique `old`, the target carries a `line` that could disambiguate and is silently discarded, and there is no ambiguity guard — a valid-but-under-specified proposal yields a silently-wrong result.

**Repro:**

```bash
cd /mnt/c/Users/csqua/Desktop/repo-librarian
python3 benchmarks/gen_corpus.py --out /tmp/l3-af1 --docs 45 --seed 1006
printf -- '---\nid: ambig\ntitle: Ambiguity test\ndomain: reference\nstatus: reference\nlast_verified: 2026-06-01\nrecheck: 90d\nread_when: [ambiguity test]\ntags: []\n---\n# Ambiguity test\n\nHistorical baseline was 379 carriers (frozen; do NOT change this line).\n\nCurrent active carriers: 379 carriers  <- THIS is the stale one to update to 412.\n' > /tmp/l3-af1/docs/reference/ambig.md
printf '%s' '{"type":"fix","targets":[{"path":"docs/reference/ambig.md","line":15}],"action":{"replace":{"old":"379 carriers","new":"412 carriers"}},"rationale":"update line 15 to 412"}' > /tmp/l3-af1/fix.json
PYTHONPATH=src python3 -m librarian.cli propose --root /tmp/l3-af1 /tmp/l3-af1/fix.json
PYTHONPATH=src python3 -m librarian.cli apply --root /tmp/l3-af1 --only p_7dbe0c53cb0c
grep -n '379\|412' /tmp/l3-af1/docs/reference/ambig.md   # line 13 wrongly -> 412, line 15 still 379
```

**Proposed regression test:** In tests/test_apply.py (FixTests): self.write('d.md', 'freeze 379 carriers\n\ncurrent 379 carriers\n'); target line=3 (the second occurrence); p = proposals.make('fix',[self.target('d.md',3)],{'replace':{'old':'379 carriers','new':'412 carriers'}}); oc=self.apply(p). Assert the frozen first line is untouched: self.assertIn('freeze 379 carriers', self.read('d.md')). Acceptable outcomes: either line 3 becomes 412 (line-aware replace) OR oc.result==ap.ERROR with an 'ambiguous'/'2 occurrences' detail. The current 'first-occurrence + applied' behavior must fail this test.

### 4. [MEDIUM] apply (merge) — REFUSED merge has already mutated the canonical, but the outcome detail and apply-log both say only 'refused' — a non-atomic partial merge misreported as a no-op

_apply_merge folds carry_over into the canonical FIRST (apply.py:321 — a non-auto-reversible frontmatter/body edit; merge risk.reversible=False), THEN calls _archive_move, which returns REFUSED when the archive dest already exists (apply.py:183-188, a realistic collision since the archive dir flattens to basename). On that path the Outcome is result=refused with a detail that mentions ONLY the archive-dest clobber, and log_outcomes writes that same result=refused to apply-log.jsonl. Nothing discloses that the canonical's tags/read_when were already changed and the redundant was left live (un-retired), producing a silent duplicated partial-merge state. An auditor trusting the 'refused / won't clobber' outcome or the audit log would wrongly conclude the working tree is unchanged. Contrast: the standalone `archive` command and the archive-only proposal both refuse cleanly with zero working-tree change — merge should be equally atomic, or must disclose the fold in the outcome and the log.

**Repro:**

```bash
cd /mnt/c/Users/csqua/Desktop/repo-librarian
python3 benchmarks/gen_corpus.py --out /tmp/f1 --docs 45 --seed 1007
mkdir -p /tmp/f1/_archive && printf 'unrelated pre-archived doc\n' > /tmp/f1/_archive/cold-chain-011.md
printf '%s' '{"type":"merge","targets":[{"path":"docs/data-platform/cold-chain-031.md"},{"path":"docs/reference/cold-chain-011.md"}],"action":{"canonical":"docs/data-platform/cold-chain-031.md","redundant":"docs/reference/cold-chain-011.md","carry_over":[{"target":"tags","content":["reefer"]},{"target":"read_when","content":["reefer questions"]}]}}' > /tmp/f1/m.json
PYTHONPATH=src python3 -m librarian.cli propose --root /tmp/f1 /tmp/f1/m.json
grep '^tags:' /tmp/f1/docs/data-platform/cold-chain-031.md   # BEFORE: tags: [cold]
PYTHONPATH=src python3 -m librarian.cli apply --root /tmp/f1 --only p_048e51dfb190   # -> [refused] won't clobber
grep -E '^(tags|read_when):' /tmp/f1/docs/data-platform/cold-chain-031.md   # AFTER: mutated despite 'refused'
cat /tmp/f1/_index/apply-log.jsonl   # logs result=refused for a run that edited the canonical
```

**Proposed regression test:** In tests/test_apply.py (MergeTests): create canonical (tags:[cold]) and redundant docs; pre-create _archive/<redundant-basename>.md so the dest is taken; p=make('merge', [canonical, redundant], {...carry_over tags:['reefer']}); oc=self.apply(p). If oc.result==ap.REFUSED then assert the canonical is byte-for-byte unchanged (self.assertNotIn('reefer', self.read(canonical))) — i.e. a refused merge is atomic. (Alternative acceptance: oc.result stays 'refused' but oc.detail explicitly says the canonical was folded; encode whichever contract you choose, but the current silent mutation must fail.)

### 5. [MEDIUM] ingest — ingest silently drops --read-when / --domain / --status / --recheck when the file already has frontmatter, and reports success (plus an inaccurate defaults disclosure)

The existing-frontmatter branch in ingest.ingest_file (ingest.py:88-91) applies only `authority` via set_field and ignores every other passed value. Ingesting a .md that already carries frontmatter while passing --read-when 'dock overbooked' --read-when 'zebra-window escalation' (and/or --domain/--status/--recheck) silently discards them: the filed doc gets NO read_when field and cannot be routed, yet the CLI prints only 'filed: _inbox/x.md -> docs/.../x.md' with no warning that the tool's core routing flags were a no-op. This violates both 'warns, never silently drops' (frontmatter) and 'fail loud, never swallow'. Merged sub-symptom (was reported separately): for the same branch cmd_ingest computes and prints a defaults_used disclosure ('NOTE: default(s) used (domain=uncategorized) -- REVIEW before trusting') even though that default is never applied (the doc keeps its own domain), so the one provenance line the operator is told to trust is itself wrong and simultaneously fails to disclose that real flags were dropped. New docs (no frontmatter) stamp read_when correctly, so the failure is specific to the already-has-frontmatter path and hidden.

**Repro:**

```bash
cd /mnt/c/Users/csqua/Desktop/repo-librarian
python3 benchmarks/gen_corpus.py --out /tmp/l3-ingest-repro/corpus --docs 45 --seed 1008
mkdir -p /tmp/l3-ingest-repro/corpus/_inbox
printf -- '---\nid: routing-doc\ntitle: Routing doc\ndomain: operations\nstatus: reference\nauthority: curated\n---\n# Routing doc\nBody.\n' > /tmp/l3-ingest-repro/corpus/_inbox/routing-doc.md
PYTHONPATH=src LIBRARIAN_TODAY=2026-07-15 python3 -m librarian.cli ingest routing-doc.md --root /tmp/l3-ingest-repro/corpus --dest docs/operations --authority curated --read-when 'dock overbooked' --read-when 'zebra-window escalation' </dev/null
grep -n read_when /tmp/l3-ingest-repro/corpus/docs/operations/routing-doc.md || echo 'NO read_when stamped -- flag silently dropped'
```

**Proposed regression test:** New test in tests/test_ingest.py: write _inbox/x.md WITH frontmatter (domain: operations, no read_when); call ingest_file(..., domain='ops', read_when=['dock overbooked']) (or drive cli.main). Assert the filed doc's read_when contains 'dock overbooked' (merge into existing frontmatter) — self.assertIn('dock overbooked', self.read(dest)). If the design instead chooses to refuse/warn, assert a warning string was emitted and the result surfaces it; the current silent success (no read_when, no warning) must fail either way. Add a second assertion that no 'default(s) used' NOTE claims a value not present in the written file.

### 6. [MEDIUM] backfill — backfill silently mints colliding ids when two paths slug to the same id (no dedup guard, unlike the registry loader)

slug() (backfill.py:29-34) collapses '/', '_', '.' and ' ' all to '-', so distinct paths (e.g. docs/reports/q1.md and docs/reports-q1.md) produce the identical id 'docs-reports-q1'. backfill --write stamps both with that same id and nothing warns: the generated catalog.json and CATALOG.md carry two entries sharing the primary routing/identity key, flags.registry_errors and flags.frontmatter_warnings are empty, and doctor reports [OK]. Any id-keyed lookup is now ambiguous — a real risk for the messy-onboarding piles backfill targets. This is asymmetric with the parallel registry path: registry.load (registry.py:45-46) DOES flag 'duplicate id' and drop the colliding entry, and apply.py already has a clobber-suffix pattern (_next_free_dest). The doc-stamping path has neither guard.

**Repro:**

```bash
cd /mnt/c/Users/csqua/Desktop/repo-librarian
rm -rf /tmp/bf-dup && mkdir -p /tmp/bf-dup/docs/reports
printf 'schema_version = 1\n[taxonomy]\ndomains = ["operations"]\n' > /tmp/bf-dup/.librarian.toml
printf '# Q1 Report (subdir)\nbody\n' > /tmp/bf-dup/docs/reports/q1.md
printf '# Reports Q1 (hyphen file)\nbody\n' > /tmp/bf-dup/docs/reports-q1.md
PYTHONPATH=src LIBRARIAN_TODAY=2026-07-15 python3 -m librarian.cli backfill --root /tmp/bf-dup --write
python3 -c "import json;d=json.load(open('/tmp/bf-dup/_index/catalog.json'));[print(e['id'],e['path']) for e in d['entries']];print('registry_errors=',d['flags']['registry_errors'],'fm_warnings=',d['flags']['frontmatter_warnings'])"
grep -n docs-reports-q1 /tmp/bf-dup/_index/CATALOG.md
```

**Proposed regression test:** New test in tests/test_backfill.py: create docs/reports/q1.md and docs/reports-q1.md (both frontmatter-less); run backfill.apply (or cli backfill --write); parse the two stamped ids from the files. Assert the two ids are DISTINCT (set of ids has len 2) OR that a collision warning was surfaced (e.g. in cmd output / a returned warnings list). Mirror apply.py's disambiguation: expect the second to become 'docs-reports-q1-2' or similar. The current identical-id, no-warning behavior must fail.

### 7. [LOW] query — query silently truncates at -n with no total/truncated indicator — a consumer cannot detect a dropped match (false-absence)

cmd_query truncates before building output (cli.py:1016 out = out[:args.n]) and then emits {'count': len(rows), 'results': rows} (cli.py:1034) — count equals results-RETURNED, not total-MATCHED, and there is no `total` or `truncated` field; the text path prints the rows with no 'showing N of M' footer. On the 51-entry seed-1001 corpus the documented default -n 50 silently omits the 51st match by path sort — sql/monthly_revenue_rollup.sql, the T5 revenue-answer artifact — from both --json and text, with no stderr note. A programmatic consumer (the agent that is the catalog's primary reader) cannot distinguish 'exactly 50 matches' from '50 of 51+', so it can falsely conclude the revenue doc is absent — the precise false-absence failure mode this catalog exists to prevent. -n 100 recovers count 51.

**Repro:**

```bash
cd /mnt/c/Users/csqua/Desktop/repo-librarian
python3 benchmarks/gen_corpus.py --out /tmp/l3-query-1001 --docs 45 --seed 1001
PYTHONPATH=src python3 -m librarian.cli query --root /tmp/l3-query-1001 --json | python3 -c "import sys,json; d=json.load(sys.stdin); ids={r['id'] for r in d['results']}; print('count', d['count'], 'extra_keys', [k for k in d if k not in ('count','results')], 'has_revenue_doc', 'monthly-revenue-rollup' in ids)"
PYTHONPATH=src python3 -m librarian.cli query --root /tmp/l3-query-1001 --json -n 100 | python3 -c "import sys,json; print('count', json.load(sys.stdin)['count'])"
```

**Proposed regression test:** New test in tests/test_query.py: create 3 matching docs, run cli.main(['query','--root',root,'--json','-n','2']) capturing stdout; parse JSON. Assert the payload exposes the cap: either a 'total' (==3) distinct from 'count' (==2), or a 'truncated': True flag. Also assert the text path (no --json) prints a 'showing 2 of 3' style footer to stdout. Current payload {'count':2,'results':[...]} with no total must fail.

### 8. [LOW] apply (fix) — A landed deletion fix (new="") false-STALEs on the documented re-propose + re-apply idempotency route

_apply_fix's row-2 idempotency branch is `elif new and new in text` (apply.py:102). For a deletion fix — action.replace.old set, new = '' (an explicitly validation-allowed form) — new is falsy, so a completed deletion can never be recognized as 'already corrected' and always falls to the both-absent row-3 STALE branch. After the deletion lands correctly, the documented idempotency route (re-propose, which rebuilds base_sha256 so the stale gate passes, then apply --only <id>) returns '[stale] ... neither old nor new text present; re-dream' and exits 1, versus the NOOP a replace-fix returns on the identical route. This is a false-STALE that the apply.py module docstring's 'run-twice == zero diff' contract warns against, and re-dreaming just reproduces the same object and false-STALEs again — there is no NOOP route for a landed deletion. No data is corrupted and it is only reachable via explicit re-propose + --only (the normal --all path gates applied proposals out), hence low.

**Repro:**

```bash
cd /mnt/c/Users/csqua/Desktop/repo-librarian
python3 benchmarks/gen_corpus.py --out /tmp/l3-af2 --docs 45 --seed 1006
printf -- '---\nid: del\ntitle: Deletion test\ndomain: reference\nstatus: reference\nlast_verified: 2026-06-01\nrecheck: 90d\nread_when: [deletion test]\ntags: []\n---\n# Deletion test\n\nRemove this parenthetical (DEPRECATED NOTE) from the sentence.\n' > /tmp/l3-af2/docs/reference/del.md
printf '%s' '{"type":"fix","targets":[{"path":"docs/reference/del.md","line":13}],"action":{"replace":{"old":" (DEPRECATED NOTE)","new":""}},"rationale":"delete deprecated parenthetical"}' > /tmp/l3-af2/del.json
PYTHONPATH=src python3 -m librarian.cli propose --root /tmp/l3-af2 /tmp/l3-af2/del.json
PYTHONPATH=src python3 -m librarian.cli apply --root /tmp/l3-af2 --only p_ea04fdb1d268   # [applied]
PYTHONPATH=src python3 -m librarian.cli propose --root /tmp/l3-af2 /tmp/l3-af2/del.json   # rebuilds base_sha256
PYTHONPATH=src python3 -m librarian.cli apply --root /tmp/l3-af2 --only p_ea04fdb1d268   # observed [stale], expected NOOP
```

**Proposed regression test:** In tests/test_apply.py (FixTests): self.write('d.md', 'remove this (X) now\n'); p=make('fix',[self.target('d.md',1)],{'replace':{'old':' (X)','new':''}}); self.assertEqual(self.apply(p).result, ap.APPLIED); after=self.read('d.md'); p2=make('fix',[self.target('d.md',1)],{'replace':{'old':' (X)','new':''}}); oc2=self.apply(p2); self.assertEqual(oc2.result, ap.NOOP)  # landed deletion re-applies as NOOP, not STALE; self.assertEqual(self.read('d.md'), after). Fix: treat 'old absent AND new=="" (deletion) with old-not-present' as NOOP, e.g. detect a completed deletion when old was a non-empty deletion target now absent.

### 9. [LOW] apply (merge) — merge carry_over does not dedup within a single content list — a repeated value is folded twice into frontmatter and baked in permanently

_fold_carry_over computes merged = cur + [w for w in want if w not in cur] (apply.py:304), which dedups `want` only against the canonical's existing values, never within `want` itself. A carry_over op with an internal duplicate — tags content ['routing','routing','optimization'] — folds 'routing' twice, yielding tags: [route, routing, routing, optimization], contradicting the documented 'read_when/tags UNION into frontmatter (dedup)' contract. The duplicate is then permanent: re-apply is an idempotent NOOP because _carry_done sees all wanted values present, so nothing ever cleans it up, polluting the catalog's tags/read_when. Cross-op dedup and the against-existing dedup both work; only the within-one-list case leaks.

**Repro:**

```bash
cd /mnt/c/Users/csqua/Desktop/repo-librarian
python3 benchmarks/gen_corpus.py --out /tmp/f2 --docs 45 --seed 1007
printf '%s' '{"type":"merge","targets":[{"path":"docs/data-platform/route-optimization-007.md"},{"path":"docs/finance/route-optimization-027.md"}],"action":{"canonical":"docs/data-platform/route-optimization-007.md","redundant":"docs/finance/route-optimization-027.md","carry_over":[{"target":"tags","content":["routing","routing","optimization"]}]}}' > /tmp/f2/m.json
PYTHONPATH=src python3 -m librarian.cli propose --root /tmp/f2 /tmp/f2/m.json
grep '^tags:' /tmp/f2/docs/data-platform/route-optimization-007.md   # BEFORE: tags: [route]
PYTHONPATH=src python3 -m librarian.cli apply --root /tmp/f2 --only p_9f58009c3844   # -> [applied]
grep '^tags:' /tmp/f2/docs/data-platform/route-optimization-007.md   # AFTER: tags: [route, routing, routing, optimization]
```

**Proposed regression test:** In tests/test_apply.py (MergeTests): canonical with tags:[route], apply a merge whose carry_over is [{'target':'tags','content':['routing','routing','optimization']}]; parse the canonical's folded tags. Assert tags == ['route','routing','optimization'] (each once). Fix: dedup within `want` order-preservingly before/while extending — e.g. build merged from cur then append each w in want only if w not already in merged.

### 10. [LOW] why — why --json emits nothing to stdout in the no-provenance first-run state, breaking the documented `--json | jq always works` contract

output.py's contract (lines 4-5) guarantees exactly one JSON document on stdout in --json mode. But cmd_why's no-provenance branch (cli.py:1051-1053) runs BEFORE the `if args.json` guard (cli.py:1063) and calls rep.say(...), which under --json is redirected to stderr — leaving stdout completely EMPTY with exit 1. `librarian why --json | jq` (or json.load) raises 'Expecting value: line 1 column 1 (char 0)'. The structurally identical no-MATCH empty state (cli.py:1063-1065) correctly emits {'count':0,'records':[]} to stdout. So two 'nothing to show' states behave inconsistently, and the one that breaks is the common first run — before any verify has produced _index/provenance.json.

**Repro:**

```bash
mkdir -p /tmp/why-noprov && printf 'schema_version = 1\n' > /tmp/why-noprov/.librarian.toml
cd /mnt/c/Users/csqua/Desktop/repo-librarian
PYTHONPATH=src python3 -m librarian.cli why --root /tmp/why-noprov --json 2>/dev/null | cat -A   # empty stdout
PYTHONPATH=src python3 -m librarian.cli why --root /tmp/why-noprov --json 2>/dev/null | python3 -c 'import sys,json;json.load(sys.stdin)'   # JSONDecodeError
mkdir -p /tmp/why-nomatch/_index && printf 'schema_version = 1\n' > /tmp/why-nomatch/.librarian.toml && printf '{"schema_version":1,"records":[{"check_id":"x","doc":"d.md","source":"s"}]}\n' > /tmp/why-nomatch/_index/provenance.json
PYTHONPATH=src python3 -m librarian.cli why --root /tmp/why-nomatch nonexistent --json 2>/dev/null   # {"count":0,"records":[]} parses fine
```

**Proposed regression test:** New test in tests/test_cli.py: minimal repo with no _index/provenance.json; run cli.main(['why','--root',root,'--json']) capturing stdout separately from stderr; assert stdout parses as JSON and equals {'count':0,'records':[]} (same as the no-match case), and the exit code is 1. Fix: move the no-provenance handling below the `if args.json` guard, or have it emit_json({'count':0,'records':[]}) in --json mode.

### 11. [LOW] backfill — backfill lifts a doc's title from a '#' comment inside a fenced code block instead of the real heading

title_of (backfill.py:37-41) scans for the first line matching '#\s+' with no fenced-code-block awareness. A frontmatter-less doc that opens with prose and a ```-fenced code block whose first line is a '#' comment (e.g. '# Install the deps first') before the doc's real ATX heading ('# Dock Scheduling Runbook') — a realistic shape for the messy onboarding docs backfill targets — gets the code comment stamped as its title, mis-describing the doc. The backfill completion/refine message tells the user to refine domain/read_when/status/authority and does NOT mention title, so the wrong title is presented as settled metadata.

**Repro:**

```bash
cd /mnt/c/Users/csqua/Desktop/repo-librarian
rm -rf /tmp/bf-fence && mkdir -p /tmp/bf-fence/docs
printf 'schema_version = 1\n[taxonomy]\ndomains = ["operations"]\n' > /tmp/bf-fence/.librarian.toml
printf 'Intro paragraph.\n\n```python\n# Install the deps first\npip install foo\n```\n\n# Dock Scheduling Runbook\n\nbody\n' > /tmp/bf-fence/docs/fenced.md
PYTHONPATH=src python3 -m librarian.cli backfill --root /tmp/bf-fence   # title = 'Install the deps first'
```

**Proposed regression test:** New test in tests/test_backfill.py: text='Intro.\n\n```python\n# Install the deps first\npip install foo\n```\n\n# Dock Scheduling Runbook\n\nbody\n'; self.assertEqual(backfill.title_of(text, 'docs/fenced.md'), 'Dock Scheduling Runbook'). Fix: track ``` fences in title_of and skip '#' lines while inside a fence (also covers ~~~ fences).

## Verified-correct (do NOT re-flag)

Verified-correct behaviors adjacent to these bugs, worth recording so they are not re-flagged: (1) _carry_done (apply.py:240-248) is PER-TARGET, so a read_when/tags phrase that merely appears in the canonical's BODY does NOT falsely count as already-folded — the whole-doc-substring false-fold is correctly guarded. (2) Cross-op and against-existing dedup in carry_over both work; only the within-a-single-content-list case leaks (bug 10). (3) The merge canonical is intentionally excluded from the generic pre-handler stale gate (apply.py:419-424) and guarded instead inside _fold_carry_over via canonical_sha256 — this is deliberate and idempotency-correct, not a bug. (4) _archive_move's clobber refusal correctly suggests a free disambiguated dest (_next_free_dest) and the standalone archive command / archive-only proposal refuse atomically with zero working-tree change — it is only the MERGE path that mutates-then-refuses (bug 4). (5) registry.load already flags duplicate ids and duplicate paths with line-level errors (registry.py:45-48), which is exactly why backfill's missing guard (bug 6) is an asymmetry rather than a global design choice. (6) applied_ids_from_log reconcile-on-read and the 5.3 intra-batch creation awareness both behave as documented. All 12 raw findings reproduced as described; none were refuted on re-verification. Not separately re-audited under time: the verify extractor/SKIP (exit-3) contract, the dream delta-gate, and scaffold hash-manifest upgrade/uninstall — these were outside the sweep's scope and had no surviving findings.