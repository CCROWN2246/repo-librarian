---
description: Refresh the knowledge base — regenerate the catalog, run the fact checks, summarize what needs attention.
allowed-tools: Bash
---
Run the knowledge-base maintenance pass from the repo root and give me a TIGHT summary (a few lines):

1. `librarian index` — regenerate `_index/` (CATALOG.md + STALENESS.md + catalog.json).
2. `librarian verify` — fact-check doc claims against their live sources.

Then report:
- catalogued count;
- **flagged** docs (provisional/draft/overdue/disputed) — the triage backlog;
- **OPEN conflicts** (quarantined disputed-claim lines) — name the doc to fix;
- `.md` **missing frontmatter** and code/data with **no registry entry** (coverage gaps);
- anything **awaiting intake** in `_inbox/`;
- any **DRIFT / CHANGED / ERROR** from verify — for a DRIFT, name the doc it says to update.

If everything is clean, say so in one line.
