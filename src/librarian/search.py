"""Pure search ranking (round-3 A1b).

Extracted from ``cli.cmd_search`` so the ``search`` command AND the ingest
conflict-check (A3) share one ranker.

- ``rank()`` is pure over catalog metadata (id/title/read_when/tags/domain);
  no I/O. It is additive-OR with a whole-phrase bonus, not strict-AND: any
  positive score is a hit, sorted by ``(-score, path)`` for determinism.
- ``rank_bodies()`` is the zero-hit fallback that re-reads doc BODIES. The
  caller gates it on ``BODY_SEARCH_MAX_DOCS`` and, above that, skips it with a
  note rather than partial-reading (a first-N-by-path partial read would risk a
  false "no match" by skipping a later doc).

Tokenization: split each arg on whitespace (so a quoted multi-word query does not
collapse to one literal substring), fold a trailing 's' (shipments->shipment).
The whole-phrase bonus keeps the RAW tokens so an exact read_when phrase matches;
per-token scoring drops stopwords but falls back to the raw tokens if that would
empty the query (an empty phrase "" substring-matches every doc).
"""

from __future__ import annotations

import re

from .config import Config

# Word tokens for claim_terms: alphanumeric runs (keeping internal ' and -).
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9'-]*")

# Above this catalogued-doc count the body fallback is skipped: a full-corpus
# read is too costly, and the token-budget guard measures the index size, not
# body-read work. Sized for the tool's target scale (~200-300 docs) with headroom.
BODY_SEARCH_MAX_DOCS = 500

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "do",
        "does",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "our",
        "the",
        "to",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "you",
    }
)


def tokens(terms: list[str]) -> list[str]:
    """Whitespace-split each arg (so a quoted phrase tokenizes) + fold trailing 's'."""
    folded = []
    for term in terms:
        for word in term.lower().split():
            if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
                word = word[:-1]
            folded.append(word)
    return folded


def _content(toks: list[str]) -> list[str]:
    return [t for t in toks if t not in _STOPWORDS] or toks


def claim_terms(text: str, *, limit: int = 80) -> list[str]:
    """Distinctive content tokens from a doc's text — the query for the ingest
    conflict-check (A3): 'what is this doc about'. Deduped (order-preserving),
    stopwords + sub-3-char tokens dropped, trailing 's' folded, capped at `limit`
    to bound the fallback body scan and keep the signal topical, not noisy."""
    seen: set[str] = set()
    out: list[str] = []
    for word in _WORD_RE.findall(text.lower()):
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        if len(word) < 3 or word in _STOPWORDS or word in seen:
            continue
        seen.add(word)
        out.append(word)
        if len(out) >= limit:
            break
    return out


def rank(entries: list[dict], terms: list[str]) -> list[tuple[float, dict]]:
    """Score catalog entries against terms (metadata only). Returns
    ``[(score, entry)]`` sorted by ``(-score, path)``; only positive scores."""
    toks = tokens(terms)
    phrase = " ".join(toks)
    content = _content(toks)
    scored: list[tuple[float, dict]] = []
    for e in entries:
        read_when = [str(x).lower() for x in e.get("read_when", [])]
        tags = [str(x).lower() for x in e.get("tags", [])]
        hay_title = str(e.get("title", "")).lower()
        hay_id = str(e.get("id", "")).lower()
        hay_domain = str(e.get("domain", "")).lower()
        score = 0.0
        if phrase and any(phrase in rw for rw in read_when):
            score += 10
        for t in content:
            score += 3 * sum(1 for rw in read_when if t in rw)
            score += 2 * sum(1 for tg in tags if t in tg)
            if t in hay_title:
                score += 2
            if t in hay_id:
                score += 1.5
            if t in hay_domain:
                score += 1
        if score > 0:
            scored.append((score, e))
    scored.sort(key=lambda x: (-x[0], x[1]["path"]))
    return scored


def routing_failures(
    entries: list[dict], target_path: str, phrases: list[str]
) -> list[tuple[str, str | None]]:
    """Which proposed `read_when` phrases fail to route to `target_path`?

    This is the falsifiability test for routing, and it exists because a drafted phrase is
    otherwise the one piece of catalog metadata nothing can check. A wrong phrase is worse
    than a missing one: missing makes a doc invisible (a false negative you notice), wrong
    makes the WRONG doc rank first for a task phrase — the exact failure this tool exists to
    prevent, and `read_when` outweighs every other field in `rank` (+10 vs +2 title).

    Deterministic and zero-token: it re-uses the same pure ranker that serves the real query,
    so "this phrase routes here" is verified by the mechanism it makes a claim about.

    Returns ``[(phrase, winning_path)]`` for each phrase that does NOT rank the target first.
    An empty list means every phrase routes where it claims to.
    """
    simulated = []
    for e in entries:
        entry = dict(e)
        if str(entry.get("path", "")) == target_path:
            entry["read_when"] = list(phrases)
        simulated.append(entry)
    if not any(str(e.get("path", "")) == target_path for e in simulated):
        return []  # target isn't catalogued yet — nothing to rank against, don't block
    failures: list[tuple[str, str | None]] = []
    for phrase in phrases:
        scored = rank(simulated, [phrase])
        winner = str(scored[0][1].get("path", "")) if scored else None
        if winner != target_path:
            failures.append((phrase, winner))
    return failures


def rank_bodies(cfg: Config, entries: list[dict], terms: list[str]) -> list[tuple[float, dict]]:
    """Zero-hit fallback: rank by doc BODY text. Reads files in the entries'
    (path-sorted) order for determinism; skips unreadable ones. The caller must
    gate on ``BODY_SEARCH_MAX_DOCS`` before calling this."""
    toks = tokens(terms)
    phrase = " ".join(toks)
    content = _content(toks)
    scored: list[tuple[float, dict]] = []
    for e in entries:
        try:
            body = cfg.path(e["path"]).read_text(encoding="utf-8").lower()
        except OSError:
            continue
        score = 0.0
        if phrase and phrase in body:
            score += 5
        for t in content:
            if t in body:
                score += 1
        if score > 0:
            scored.append((score, e))
    scored.sort(key=lambda x: (-x[0], x[1]["path"]))
    return scored
