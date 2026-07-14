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

from .config import Config

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
