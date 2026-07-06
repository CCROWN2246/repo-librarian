# Benchmark results (running log — methodology evolves, all runs kept)

## Run 2 — 2026-07-06 · session mode · corpus v2 (200 docs, stale echoes, de-labeled bodies, verify-only task)

One agent per condition answered all 8 tasks in a single session (catalog paid once —
the realistic accounting). Same model both sides (Claude Fable 5 Explore subagents).

| | Librarian | Bare |
|---|---|---|
| Accuracy | **8/8** | 7/8 |
| Q8 (verify-only: live value in NO doc) | **93 — ran the registered check, saw the 87 baseline had drifted, quoted live** | refused to quote ("pull it live") but **never found the warehouse; no answer** |
| Stale/false facts asserted | 0 | 0 |
| Provenance cited per answer | every answer (authority + freshness) | most answers |
| Session tokens | 40,309 | 17,858 |
| Tool calls + commands | 7 + 6 | 8 + 2 |

**The honest headline, consistent across Run 1, Run 2, and the origin project's spike:**

> Against a frontier agent on a decently-named corpus, repo-librarian does **not** save
> tokens — it costs roughly 2× per session (~22k premium here: catalog + protocol +
> verify runs) and **buys correctness**: the answer no document holds (live verify),
> explicit authority/freshness grounding on every claim, and refusal-with-a-path
> instead of refusal-empty-handed.

Where the premium concentrates: the always-load catalog (~7.5k tokens at 204 entries —
bounded, amortized across a session) and the verify executions. Where it pays for
itself: any fact whose truth lives outside the docs, any corpus where drift echoes
outnumber the authoritative source, and any deliverable where one stale number costs
more than 22k tokens (i.e., most exec decks).

Baseline respect: modern agents grep *very* well. Run 1's distractor and stale-trap
tasks were all solved by the bare agent reading candidate docs and reasoning about
freshness in-band. The tool's edge is narrowest on lookup tasks and widest on
live-truth and provenance tasks — design your KB (and your expectations) accordingly.

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
