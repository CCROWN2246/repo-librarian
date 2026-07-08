"""Enrichment gap detection — the deterministic half of B5.

This is where the librarian stops being a passive catalog and becomes an active
analyst: it NAMES the questions the corpus can't answer yet, so the /librarian-enrich
agent can query a live source and draft a source-verified provisional doc. Pure +
deterministic: it only surfaces gaps + the sources available to fill them. The agent
supplies the query and the generative draft; the accuracy wall lives in the schema
(enrich_create must carry non-empty source evidence, is always provisional, and ships
with a paired add_check) so a drafted fact can never masquerade as verified.

Two gap kinds, per the Phase-2 decision:
  uncovered           a code/data file the coverage scan flags with no doc/registry entry
  confirmed_absence   a "we don't have X" claim the dream absence-audit judged a REAL gap
                      (a resolve_absence proposal with verdict == "confirmed_gap")
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import CatalogResult
from .config import Config


@dataclass
class Gap:
    kind: str  # "uncovered" | "confirmed_absence"
    ref: str  # file path (uncovered) or "doc:line" (confirmed_absence)
    detail: str
    domain: str = ""

    def to_dict(self) -> dict:
        return {"kind": self.kind, "ref": self.ref, "detail": self.detail, "domain": self.domain}


def detect_gaps(cfg: Config, res: CatalogResult, proposals_list: list) -> list[Gap]:
    """Deterministic enrichment worklist. `proposals_list` is the loaded proposals.json
    (list of Proposal); confirmed-gap absence claims come from it."""
    gaps: list[Gap] = []
    for f in sorted(res.uncovered):
        gaps.append(Gap(kind="uncovered", ref=f, detail=f"no doc or registry entry covers {f}"))
    for p in proposals_list:
        if p.type == "resolve_absence" and p.action.get("verdict") == "confirmed_gap":
            t = p.targets[0]
            loc = f"{t.path}:{t.line}" if t.line is not None else t.path
            gaps.append(
                Gap(
                    kind="confirmed_absence",
                    ref=loc,
                    detail=p.rationale or "dream-audited confirmed gap",
                    domain=str(p.action.get("domain", "")),
                )
            )
    gaps.sort(key=lambda g: (g.kind, g.ref))
    return gaps
