"""The dream cycle's deterministic half: build the worklist, gate the spend.

Philosophy (see docs/dream.md): the CLI decides *what* needs judgment — for zero
tokens — and an agent (`/librarian-dream`) exercises the judgment, propose-only, on a
branch. Three job types survive scope triage:

  open_conflicts   OPEN KB-CONTRADICTED lines that need a drafted resolution
  merge_candidates pairs of docs in the same domain whose title/read_when/tags
                   overlap enough to smell like duplicates
  read_when_todos  entries with empty or TODO routing phrases
  absence_claims   confident "we don't have X" lines to audit against the catalog
  retirement       docs marked with a terminal status (retired/superseded/…) that
                   still live in the docs tree — positive-evidence archive candidates

The delta gate: a content hash of the worklist is stamped on `--mark-done`
(_index/.last_dream). A dream is DUE only when the worklist is non-empty AND
(it changed since the last dream, or the same items have sat unreviewed past
[dream].nudge_after_days). Most sessions: nothing due, zero cost.

Two builders share one core so `status --hook` can compute the worklist from
catalog.json (no filesystem walk) while `dream` rebuilds it fresh from disk.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field

from .catalog import CatalogResult
from .config import Config

STATE_FILE = ".last_dream"
DEFAULT_MERGE_SIMILARITY = 0.6
MAX_MERGE_CANDIDATES = 10
# Terminal statuses that mean "the author already retired this" — positive evidence
# for a propose-only archive. A doc carrying one but still living in the docs tree
# (not yet moved to the archive dir) is a retirement candidate. Conservative by design
# (R3): status is an explicit author signal, never an inference.
RETIRED_STATUSES = {"retired", "superseded", "archived", "obsolete", "deprecated", "shipped", "done"}
_WORD = re.compile(r"[a-z0-9]+")
# generic words that shouldn't drive doc-similarity
_STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "for",
    "to",
    "in",
    "on",
    "with",
    "how",
    "notes",
    "note",
    "doc",
    "docs",
    "reference",
    "guide",
}


@dataclass
class Worklist:
    open_conflicts: list[dict] = field(default_factory=list)
    merge_candidates: list[dict] = field(default_factory=list)
    read_when_todos: list[dict] = field(default_factory=list)
    absence_claims: list[dict] = field(default_factory=list)
    retirement_candidates: list[dict] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (
            self.open_conflicts
            or self.merge_candidates
            or self.read_when_todos
            or self.absence_claims
            or self.retirement_candidates
        )

    @property
    def total(self) -> int:
        return (
            len(self.open_conflicts)
            + len(self.merge_candidates)
            + len(self.read_when_todos)
            + len(self.absence_claims)
            + len(self.retirement_candidates)
        )

    def counts(self) -> dict[str, int]:
        return {
            "open_conflicts": len(self.open_conflicts),
            "merge_candidates": len(self.merge_candidates),
            "read_when_todos": len(self.read_when_todos),
            "absence_claims": len(self.absence_claims),
            "retirement_candidates": len(self.retirement_candidates),
        }

    def to_dict(self) -> dict:
        return {
            "open_conflicts": self.open_conflicts,
            "merge_candidates": self.merge_candidates,
            "read_when_todos": self.read_when_todos,
            "absence_claims": self.absence_claims,
            "retirement_candidates": self.retirement_candidates,
            "counts": self.counts(),
        }

    def content_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _entry_path(e: dict) -> str:
    return e.get("_path") or e.get("path") or ""


def _tokens(entry: dict) -> set[str]:
    parts = [str(entry.get("title", ""))]
    for key in ("read_when", "tags"):
        val = entry.get(key, [])
        if isinstance(val, list):
            parts.extend(str(x) for x in val)
    words: set[str] = set()
    for p in parts:
        words.update(_WORD.findall(p.lower()))
    return words - _STOP


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def merge_candidates(entries: list[dict], threshold: float = DEFAULT_MERGE_SIMILARITY) -> list[dict]:
    """Same-domain doc pairs whose metadata overlap smells like duplication.

    Deterministic pre-filter only — the agent judges whether a merge is real.
    O(n^2) within each domain; trivial at the tool's target scale (<=~300 docs).
    """
    by_domain: dict[str, list[tuple[dict, set[str]]]] = {}
    for d in entries:
        if d.get("kind") != "doc" or d.get("status") in ("archived", "retired"):
            continue
        by_domain.setdefault(str(d.get("domain", "")), []).append((d, _tokens(d)))
    out = []
    for domain in sorted(by_domain):
        group = by_domain[domain]
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                (d1, t1), (d2, t2) = group[i], group[j]
                sim = _jaccard(t1, t2)
                if sim >= threshold:
                    pa, pb = sorted([_entry_path(d1), _entry_path(d2)])
                    out.append({"a": pa, "b": pb, "domain": domain, "similarity": round(sim, 3)})
    out.sort(key=lambda x: (-x["similarity"], x["a"], x["b"]))
    return out[:MAX_MERGE_CANDIDATES]


def _read_when_todos(entries: list[dict]) -> list[dict]:
    out = []
    for d in sorted(entries, key=_entry_path):
        rw = d.get("read_when", [])
        if not isinstance(rw, list):
            continue
        if not rw or any("todo" in str(x).lower() for x in rw):
            out.append(
                {
                    "path": _entry_path(d),
                    "id": str(d.get("id", "?")),
                    "kind": d.get("kind", "?"),
                    "title": str(d.get("title", "")),
                    "domain": str(d.get("domain", "")),
                    "read_when": [str(x) for x in rw],
                }
            )
    return out


def retirement_candidates(entries: list[dict]) -> list[dict]:
    """Docs the author already marked terminal (RETIRED_STATUSES) but that still live
    in the docs tree. Deterministic positive evidence; the agent confirms and the
    proposal is a reversible archive (never an auto-delete)."""
    out = []
    for d in sorted(entries, key=_entry_path):
        if d.get("kind") != "doc":
            continue
        status = str(d.get("status", "")).lower()
        if status in RETIRED_STATUSES:
            out.append(
                {
                    "path": _entry_path(d),
                    "id": str(d.get("id", "?")),
                    "title": str(d.get("title", "")),
                    "status": status,
                    "evidence": f"status={status}",
                }
            )
    return out


def _build(
    entries: list[dict], conflicts: list[dict], absence: list[dict], merge_threshold: float
) -> Worklist:
    return Worklist(
        open_conflicts=sorted(conflicts, key=lambda c: (c["path"], c["line"])),
        absence_claims=sorted(absence, key=lambda c: (c["path"], c["line"])),
        merge_candidates=merge_candidates(entries, merge_threshold),
        read_when_todos=_read_when_todos(entries),
        retirement_candidates=retirement_candidates(entries),
    )


def from_catalog_result(res: CatalogResult, merge_threshold: float = DEFAULT_MERGE_SIMILARITY) -> Worklist:
    conflicts = [{"path": p, "line": i, "text": t} for p, i, t in res.conflicts]
    absence = [{"path": p, "line": i, "text": t} for p, i, t in res.absence_claims]
    return _build(res.items, conflicts, absence, merge_threshold)


def from_catalog_json(data: dict, merge_threshold: float = DEFAULT_MERGE_SIMILARITY) -> Worklist:
    flags = data.get("flags", {})
    return _build(
        data.get("entries", []),
        list(flags.get("open_conflicts", [])),
        list(flags.get("absence_claims", [])),
        merge_threshold,
    )


def load_state(cfg: Config) -> dict:
    path = cfg.path(cfg.index_dir) / STATE_FILE
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def mark_done(cfg: Config, wl: Worklist, now: int | None = None) -> None:
    out = cfg.path(cfg.index_dir)
    out.mkdir(parents=True, exist_ok=True)
    state = {
        "done_at": int(now if now is not None else time.time()),
        "worklist_hash": wl.content_hash(),
        "counts": wl.counts(),
    }
    (out / STATE_FILE).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def is_due(cfg: Config, wl: Worklist, now: float | None = None) -> tuple[bool, str]:
    """(due, reason). Never due when the worklist is empty or nudging is off."""
    if cfg.dream_nudge_after_days <= 0:
        return False, "dream nudge disabled ([dream].nudge_after_days = 0)"
    if wl.empty:
        return False, "nothing to dream about — worklist is empty"
    state = load_state(cfg)
    if not state:
        return True, "never dreamt and the worklist is non-empty"
    if state.get("worklist_hash") != wl.content_hash():
        return True, "the worklist changed since the last dream"
    now = time.time() if now is None else now
    age_days = (now - state.get("done_at", 0)) / 86400
    if age_days > cfg.dream_nudge_after_days:
        return True, f"same items unreviewed for {int(age_days)}d (> {cfg.dream_nudge_after_days}d)"
    return False, "already dreamt about these items recently"
