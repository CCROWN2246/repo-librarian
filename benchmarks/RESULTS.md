# Benchmark results (running log — methodology evolves, all runs kept)

## Run 1 — 2026-07-06 · per-task cold agents · corpus v1 (200 docs, seed 7)

Setup: 7 golden tasks × 2 conditions (librarian-enabled vs bare copy of the same corpus),
one cold read-only agent per task (Claude Fable 5 "Explore" subagents). Token figure =
total agent tokens reported by the harness for that task.

| Task | Type | Librarian: correct / tokens / tools | Bare: correct / tokens / tools |
|---|---|---|---|
| T1 | locate-distinctive | ✅ 18,693 / 4 | ✅ 15,055 / 3 |
| T2 | common-term routing | ✅ 32,856 / 3 | ✅ 12,532 / 3 |
| T3 | stale-fact trap | ✅ 32,561 / 6 | ✅ 18,422 / 6 |
| T4 | absence claim | ✅ 32,687 / 3 | ✅ 12,253 / 3 |
| T5 | artifact routing | ✅ 32,473 / 3 | ✅ 11,199 / 2 |
| T6 | provisional flag | ✅ 32,638 / 3 | ✅ 12,207 / 2 |
| T7 | quarantined claim | ✅ 31,524 / 2 | ✅ 12,543 / 5 |
| **Mean** | | **7/7 · ~30,490** | **7/7 · ~13,459** |

**Verdict: no discrimination — and the librarian condition cost ~2.3× more tokens.**
We publish this because the failure is instructive:

1. **The corpus was too honest.** The authoritative docs self-label in their *bodies*
   ("canonical definitions", "412 as of 2026-06", "PROVISIONAL — do not report as
   final") and the planted files have guessable names. A strong grepping agent gets
   the metadata's value from the prose for free. Real drift doesn't announce itself.
2. **Per-task accounting is unfair to a session tool.** Each librarian agent paid the
   full catalog read (~7.5k tokens at 204 entries) for a single lookup. Real sessions
   amortize one catalog read across many lookups.
3. **The quarantine convention worked without the tool** (T7 bare read the
   `KB-CONTRADICTED` marker inline and answered correctly) — evidence for the
   *convention*, neutral on the *tooling*.
4. Baseline agents are elite greppers; that is the correct, hardest baseline to keep.

## Run 2 design changes (corpus v2)

- **Stale echoes**: the outdated carrier count propagates into three narrative docs,
  two of them *fresher-dated* than the authoritative doc — recency heuristics now pick
  wrong; authority-over-recency (the librarian rule) picks right.
- **De-labeled bodies**: authority/freshness/provisional signals live only in
  frontmatter + the catalog, not restated in prose — the realistic case (nobody writes
  "authority: verified" in a sentence).
- **Session mode**: one agent per condition answers *all* tasks in one pass; report
  total session tokens + per-task correctness. This is how the tool is actually used.
- **A verify-only task**: the current value exists in *no* doc — only the live source
  (reachable via the check registry / `librarian verify`) has it.
