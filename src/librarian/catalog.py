"""The catalog engine: unified doc+artifact model with staleness/conflict/coverage flags.

Pure — takes (config, today) plus preloaded artifacts, returns a CatalogResult.
All file writing lives in render.py / the CLI layer.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

from . import frontmatter, scanner
from .config import Config

# Absence-claim guard: a doc can confidently assert a gap the KB fills elsewhere.
# The conflict protocol only checks claims against verified facts, not *absence*
# claims, so it misses this. Advisory only — many hits are legitimate TODOs; the
# point is a human eyeball: "is this 'we don't have X' actually true?"
ABSENCE_RE = re.compile(
    r"(not yet identified|not identified|\bTBD\b|to be determined|no source|"
    r"we don'?t have|does ?n'?t exist|no such (?:doc|source|dataset)|never captured)",
    re.I,
)
# Conflict markers: the on-disk quarantine format written into doc bodies. New product
# vocab (`librarian:disputed` / `librarian:ack`) is written going forward; the legacy
# `KB-` tokens are still PARSED so docs written before the rename keep working (dual-parse).
DISPUTED_MARKERS = ("<!-- librarian:disputed", "<!-- KB-CONTRADICTED")
ACK_TOKENS = ("librarian:ack", "KB-ACK")
CONFLICT_MARKER = DISPUTED_MARKERS[0]  # canonical (new) form for callers that reference it
ABSENCE_SKIP_LINE = (
    "KB-CONTRADICTED",
    "KB-ACK",
    "librarian:disputed",
    "librarian:ack",
    "absence-claim",
    "ABSENCE_",
)


@dataclass
class CatalogResult:
    items: list[dict] = field(default_factory=list)  # present docs + artifacts
    missing_fm: list[str] = field(default_factory=list)
    fm_warnings: list[tuple[str, str]] = field(default_factory=list)  # (path, warning)
    stale: list[tuple[str, str, str]] = field(default_factory=list)  # (id, path, why)
    orphans: list[tuple[str, str]] = field(default_factory=list)  # (id, path)
    conflicts: list[tuple[str, int, str]] = field(default_factory=list)
    conflicts_ack: list[tuple[str, int, str]] = field(default_factory=list)
    absence_claims: list[tuple[str, int, str]] = field(default_factory=list)
    unverified: list[dict] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)
    inbox_pending: list[str] = field(default_factory=list)
    registry_errors: list[str] = field(default_factory=list)

    @property
    def n_docs(self) -> int:
        return sum(1 for d in self.items if d["kind"] == "doc")

    @property
    def n_artifacts(self) -> int:
        return len(self.items) - self.n_docs

    def by_domain(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for d in self.items:
            out.setdefault(d.get("domain", "(none)"), []).append(d)
        return out

    def summary(self) -> dict:
        return {
            "catalogued": len(self.items),
            "docs": self.n_docs,
            "artifacts": self.n_artifacts,
            "domains": len(self.by_domain()),
            "missing_frontmatter": len(self.missing_fm),
            "frontmatter_warnings": len(self.fm_warnings),
            "unregistered": len(self.uncovered),
            "flagged": len(self.stale),
            "orphans": len(self.orphans),
            "open_conflicts": len(self.conflicts),
            "acknowledged_conflicts": len(self.conflicts_ack),
            "absence_claims": len(self.absence_claims),
            "unverified_sources": len(self.unverified),
            "inbox_pending": len(self.inbox_pending),
            "registry_errors": len(self.registry_errors),
        }

    def gate_failures(self, fail_on: list[str]) -> list[str]:
        """Categories from [index].fail_on that are non-empty (for `index --check`)."""
        counts = {
            "missing_frontmatter": len(self.missing_fm),
            "unregistered": len(self.uncovered),
            "orphans": len(self.orphans),
            "open_conflicts": len(self.conflicts),
            "taxonomy": sum(1 for (_, _, why) in self.stale if "taxonomy" in why),
            "fm_warnings": len(self.fm_warnings),
        }
        return [c for c in fail_on if counts.get(c, 0)]


def _days_old(value, today: datetime.date) -> int | None:
    try:
        return (today - datetime.date.fromisoformat(str(value))).days
    except (ValueError, TypeError):
        return None


def _recheck_days(value) -> int | None:
    m = re.match(r"(\d+)\s*d", str(value))
    return int(m.group(1)) if m else None


def build(
    cfg: Config, today: datetime.date, artifacts: list[dict], registry_errors: list[str] | None = None
) -> CatalogResult:
    res = CatalogResult(registry_errors=list(registry_errors or []))
    all_files = scanner.walk_files(cfg)
    md = scanner.md_files(cfg, all_files)
    res.inbox_pending = scanner.inbox_pending(cfg)

    absence_res = [ABSENCE_RE]
    for pat in cfg.absence_extra_patterns:
        try:
            absence_res.append(re.compile(pat, re.I))
        except re.error as e:
            res.registry_errors.append(f"[index].absence_extra_patterns: bad regex {pat!r}: {e}")

    items: list[dict] = []
    bodies: dict[str, str] = {}
    for path in md:
        try:
            text = cfg.path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            res.fm_warnings.append((path, f"unreadable: {e}"))
            continue
        bodies[path] = text
        parsed = frontmatter.parse(text)
        if parsed is None:
            res.missing_fm.append(path)
            continue
        for w in parsed.warnings:
            res.fm_warnings.append((path, w))
        meta = dict(parsed.meta)
        meta["_path"] = path
        meta["kind"] = "doc"
        items.append(meta)

    reg_paths: set[str] = set()
    for a in artifacts:
        a = dict(a)
        a["_path"] = a["path"]
        a.setdefault("kind", "artifact")
        reg_paths.add(a["path"])
        if not cfg.path(a["path"]).exists():
            res.orphans.append((a.get("id", a["path"]), a["path"]))
            continue
        items.append(a)

    closed_domains = set(cfg.domains)
    for d in items:
        req = cfg.required_doc_fields if d["kind"] == "doc" else cfg.required_artifact_fields
        reasons = []
        miss = [f for f in req if f not in d or d[f] in ("", None)]
        if miss:
            reasons.append("missing fields: " + ",".join(miss))
        if d.get("status") in ("provisional", "draft"):
            reasons.append("status=" + str(d["status"]))
            # Enrichment quarantine (R1): a provisional doc unreviewed past the decay TTL
            # is called out as un-audited so generated drafts can't quietly become furniture.
            if d.get("status") == "provisional" and cfg.enrich_provisional_ttl_days > 0:
                pv_age = _days_old(d.get("last_verified", ""), today)
                if pv_age is not None and pv_age > cfg.enrich_provisional_ttl_days:
                    reasons.append(
                        f"un-audited enrichment {pv_age}d (> TTL {cfg.enrich_provisional_ttl_days}d)"
                    )
        if str(d.get("has_disputed_claims", "")).lower() == "true":
            reasons.append("has disputed claims")
        rd = _recheck_days(d.get("recheck", ""))
        age = _days_old(d.get("last_verified", ""), today)
        if rd is not None and age is not None and age > rd:
            reasons.append(f"overdue ({age}d > recheck {rd}d)")
        if closed_domains and d.get("domain") and d["domain"] not in closed_domains:
            reasons.append(f"taxonomy: domain {d['domain']!r} not in [taxonomy].domains")
        if d.get("status") and d["status"] not in cfg.statuses:
            reasons.append(f"taxonomy: status {d['status']!r} not in [taxonomy].statuses")
        if reasons:
            res.stale.append((str(d.get("id", d["_path"])), d["_path"], "; ".join(reasons)))

    res.uncovered = scanner.uncovered(cfg, all_files, reg_paths)

    for path in md:
        body = bodies.get(path)
        if body is None:
            continue
        for i, line in enumerate(body.splitlines(), 1):
            # Require the literal HTML-comment marker form so docs that merely
            # *describe* the convention in prose/backticks don't false-positive.
            if any(m in line for m in DISPUTED_MARKERS):
                acked = any(a in line for a in ACK_TOKENS)
                target = res.conflicts_ack if acked else res.conflicts
                target.append((path, i, line.strip()[:140]))
            if cfg.absence_guard and not any(s in line for s in ABSENCE_SKIP_LINE):
                if any(rx.search(line) for rx in absence_res):
                    res.absence_claims.append((path, i, line.strip()[:140]))

    res.unverified = [d for d in items if str(d.get("authority", "curated")).lower() == "unverified"]
    res.items = items
    return res
