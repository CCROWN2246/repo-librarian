"""Bulk-stamp skeleton frontmatter onto .md docs that lack it.

The fastest way to onboard an existing pile of docs: walk a directory, find
every .md with no frontmatter, prepend a skeleton (id from the path, title from
the first heading, status=draft so it surfaces as a triage item). Idempotent —
files that already have frontmatter are untouched. Dry-run by default.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import frontmatter
from .config import Config


@dataclass
class BackfillPlan:
    path: str  # repo-relative
    id: str
    title: str


def slug(rel: str) -> str:
    s = re.sub(r"\.md$", "", rel)
    s = s.replace(os.sep, "-").replace("/", "-").replace(" ", "-").replace("_", "-").lower()
    s = re.sub(r"[^a-z0-9-]+", "-", s).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return s or "doc"


def title_of(text: str, rel: str) -> str:
    for line in text.splitlines():
        m = re.match(r"#\s+(.*)", line.strip())
        if m:
            return m.group(1).strip().strip('"')
    base = re.sub(r"\.md$", "", os.path.basename(rel)).replace("-", " ").replace("_", " ")
    return base.strip().title() or "Untitled"


def skeleton(
    rel: str, text: str, *, domain: str, status: str, authority: str | None, recheck: str, today: date
) -> str:
    meta = {"id": slug(rel), "title": title_of(text, rel), "domain": domain, "status": status}
    if authority:
        meta["authority"] = authority
    meta.update(last_verified=today.isoformat(), recheck=recheck, read_when=[], owner="", tags=[])
    return frontmatter.serialize(meta) + text


def plan(cfg: Config, target: str | None = None) -> list[tuple[Path, BackfillPlan, str]]:
    """(abspath, plan, text) for every .md under `target` lacking frontmatter."""
    base = cfg.path(target) if target else cfg.path(cfg.docs_dir)
    skip = cfg.all_skip_dirs
    out = []
    for dp, dns, fns in os.walk(base):
        dns[:] = sorted(d for d in dns if d not in skip)
        for f in sorted(fns):
            if not f.endswith(".md") or f in set(cfg.skip_files):
                continue
            ap = Path(dp) / f
            rel = os.path.relpath(ap, cfg.root).replace(os.sep, "/")
            try:
                text = ap.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if frontmatter.find_block(text) is not None:
                continue
            out.append((ap, BackfillPlan(path=rel, id=slug(rel), title=title_of(text, rel)), text))
    return out


def apply(
    cfg: Config,
    targets: list[tuple[Path, BackfillPlan, str]],
    *,
    domain: str,
    status: str,
    authority: str | None,
    recheck: str,
    today: date,
) -> int:
    for ap, p, text in targets:
        ap.write_text(
            skeleton(
                p.path, text, domain=domain, status=status, authority=authority, recheck=recheck, today=today
            ),
            encoding="utf-8",
        )
    return len(targets)
