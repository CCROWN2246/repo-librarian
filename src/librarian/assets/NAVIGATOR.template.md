---
id: navigator
title: Navigator — task→doc routing
domain: reference
status: draft
last_verified: 2026-01-01
recheck: 60d
read_when: [where do I find, what should I read for, routing]
owner: ""
tags: [navigator, routing]
---
# NAVIGATOR — routing layer for this repo

**Read this first.** Fresh sessions auto-load only the agent instruction file. Everything else is opened
deliberately. This file maps the task at hand → the docs to read, so the agent doesn't re-derive tribal
knowledge or miss context. **All paths are relative to the repo root.**

> Maintainer rule: adding a new doc = add **one row** to the right table here. Don't reproduce content.
> This is a TEMPLATE — replace the bracketed examples with your real domains, docs, and traps, then set
> `status: authoritative`.

---

## TIER 1 — Always load (every session, any task)
| File | What to read | Why |
|---|---|---|
| `_index/CATALOG.md` | The whole inventory by `domain` | What knowledge exists + where. |
| `_index/STALENESS.md` | Flagged / overdue / conflicts / inbox | What needs attention before you trust it. |
| `AGENTS.md` / `CLAUDE.md` (auto-loaded) | The Knowledge protocol + repo conventions | How to operate; what not to violate. |

## TIER 2 — Task-type routing (read BEFORE starting the task)
> One section per recurring task type. Example scaffold — replace with yours.

### A. [Task type — e.g. "Answer a question about <topic>"]
| Read | Why it's load-bearing |
|---|---|
| `<path/to/doc>` | <the one reason this doc matters for this task> |

### B. [Task type — e.g. "Work with the <X> dataset / query"]
| Read | Why it's load-bearing |
|---|---|
| `<path/to/query-or-export>` | <grain, gotcha, as-of date> |

## TIER 3 — Cheat sheet (failures crystallized — scan in 60s)
> The traps that cost someone an afternoon. Add a row each time you hit one.

| Trap | Reality |
|---|---|
| <e.g. "this export looks current"> | <e.g. "it's a Jan snapshot; re-run the query for live"> |

---

## ON-DEMAND — everything else (findable via CATALOG, not routed here)
| File | Use when |
|---|---|
| `<path>` | <when you'd reach for it> |
