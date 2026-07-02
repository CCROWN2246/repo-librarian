# NAVIGATOR authoring guide

`docs/NAVIGATOR.md` (scaffolded as a template by `librarian init`) is the task→doc
routing layer: CATALOG tells the agent *what exists*; NAVIGATOR tells it *what to read
for the task at hand*. In a small repo (< ~15 docs) CATALOG alone is enough — skip
NAVIGATOR until routing mistakes actually happen.

## The three-tier structure

**Tier 1 — always load.** The 2–4 things every session needs: the catalog, the
staleness report, the instruction file. Keep it under five rows.

**Tier 2 — task-type routing.** One section per *recurring task type* ("edit the live
dashboard", "write a warehouse query", "answer a metric-definition question"), each a
table of `| Read | Why it's load-bearing |`. The "why" column is the load-bearing part
— one sentence on what breaks if you skip it. If you can't write that sentence, the
row doesn't belong.

**Tier 3 — the cheat sheet.** Crystallized traps: `| Trap | Reality |`. The entry bar:
*this cost someone an afternoon.* Real examples from the origin project: "CLI default
region is us-east-2 but everything lives in us-east-1"; "a clean deploy ≠ it renders —
STRICT validation only catches schema errors." Add a row each time you get burned;
this table compounds into the most valuable file in the repo.

Everything else is **on-demand**: findable via CATALOG, deliberately not routed.

## Maintainer rules

1. **New doc = one row here.** Never reproduce content in NAVIGATOR — it routes, it
   doesn't teach. Duplicated content is how routing layers rot.
2. NAVIGATOR is itself a knowledge doc: it has frontmatter, a `recheck`, and goes
   stale like everything else. The template ships as `status: draft` so it stays on
   the triage list until you've replaced the placeholders and promoted it.
3. Retire task-type sections when the task type dies (project shipped, system
   retired) — move crystallized traps worth keeping down into Tier 3.

## Anti-patterns

- A NAVIGATOR that lists every file (that's CATALOG's job — generated, always current).
- "Why" columns that restate the title ("read the schema doc because it has the schema").
- Routing by folder path instead of task ("everything in docs/etl/") — tasks cut
  across folders; that's the point of a routing layer.
