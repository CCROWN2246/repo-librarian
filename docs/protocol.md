# The librarian protocol

The behavioral half of the system. The mechanical half (the CLI) only pays off if the
agent operating in your repo follows these rules — which is why `librarian init` puts
the condensed version in `AGENTS.md`/`CLAUDE.md` where agents auto-load it, and the
full text in `KNOWLEDGE_PROTOCOL.md` at the repo root.

The canonical text ships with the package and is scaffolded into your repo; this page
explains the *why* behind each rule.

## Never read the whole corpus

Reading everything is a token bonfire and — worse — it doesn't scale with corpus
growth. The catalog inverts it: ~1–2k tokens of always-on inventory
(`_index/CATALOG.md` + `STALENESS.md`), then open exactly the docs that fit.

## The five reflexes

1. **Find** — route via `domain` + `read_when` + grep. The empirical lesson behind
   this (measured in the origin project): grep ranks the doc that *mentions* a term
   most, which for common terms is a narrative doc, not the authoritative reference.
   `read_when` is written by the author who knows which doc you should open.
   The **absence-claim guard**: before asserting the KB *lacks* something, positively
   check the catalog + grep. This exists because of a real bug — a strategy doc
   confidently said a KPI source was "not yet identified" while the requirements doc
   holding that source sat right beside it. Conflict-checking compares claims against
   verified facts; an absence-claim contradicts nothing, so nothing catches it — except
   this reflex (and the advisory table `librarian index` builds).
2. **Re-route on drift** — first-doc anchoring is the failure mode: the agent keeps
   answering from whatever it opened first. When the task shifts, re-scan.
3. **Freshness gate** — `last_verified` vs `recheck` is the contract that a fact was
   checked, and when. If the fact has a `[[verify.checks]]` entry, `librarian verify`
   is the re-check; if not, the source is the registered query/export/notebook that
   produced it. Correctness-critical facts deserve a check — that's what promotes a doc
   to `authority: verified` honestly.
4. **Capture on discovery** — knowledge that stays in a chat transcript is lost. New
   durable fact → doc or registry entry → `librarian index`. Checkable fact → also a
   check, so it can never silently rot.
5. **Trust by tier, conflicts by authority — never by recency** — the newest statement
   is not the truest; the *best-grounded* one is. `verified > curated > unverified`.
   The quarantine mechanic (`KB-CONTRADICTED` markers) preserves context without
   letting a falsehood circulate as fact — see [conflict resolution](conflicts.md).

## Layers

A fact can be true at one layer of a pipeline and false at another. The canonical
example from the origin project: a timestamp column existed in the production OLTP
database but was dropped from the warehouse copy — so "the column exists" was
simultaneously true (raw layer) and false (warehouse layer). If your repo has a
pipeline, tag verify sources by layer and word facts layer-qualified. Never assume a
fact transfers across layers without a check on each side.

## What the tooling enforces vs what the agent must do

| Concern | Tooling | Agent |
|---|---|---|
| Inventory & coverage | `librarian index` flags gaps | registers new artifacts |
| Freshness | `verify`, staleness flags, the hook nudge | actually re-checks before asserting |
| Conflicts | detects markers, lists OPEN ones | quarantines, resolves, surfaces to the user |
| Routing | `search`, CATALOG, NAVIGATOR | opens the *fitting* docs, re-routes on drift |
| Intake | inbox counter, `ingest` | assigns honest authority tiers |
