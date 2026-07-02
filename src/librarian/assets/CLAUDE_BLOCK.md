## Knowledge protocol

Follow the **librarian protocol** in `AGENTS.md` (full reference: `KNOWLEDGE_PROTOCOL.md`): start every
session from `_index/CATALOG.md` + `_index/STALENESS.md`, route via `domain`/`read_when` instead of
reading the whole corpus, freshness-gate facts (`librarian verify`), capture discoveries back into docs,
and resolve conflicts by authority tier — never by recency.
