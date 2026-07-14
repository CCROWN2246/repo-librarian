"""Filesystem walking: doc discovery, inbox listing, coverage scan."""

from __future__ import annotations

import fnmatch
import os

from .config import Config


def walk_files(cfg: Config) -> list[str]:
    """All files under the docs dir, relative to root, sorted; skip rules applied."""
    base = cfg.path(cfg.docs_dir)
    skip = cfg.all_skip_dirs
    out = []
    for dp, dns, fns in os.walk(base):
        dns[:] = sorted(d for d in dns if d not in skip and not d.endswith(".egg-info"))
        for f in fns:
            rel = os.path.relpath(os.path.join(dp, f), cfg.root)
            out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def md_files(cfg: Config, all_files: list[str]) -> list[str]:
    # 7.1: skip_files entries are basename GLOBS (fnmatch), so "FEEDBACK*.md" covers
    # every round without hand-editing the list. fnmatchcase (not fnmatch) keeps the
    # match case-sensitive on every OS — Windows case-folding would be a determinism
    # hazard. A wildcard-free pattern matches exactly as the old basename set did.
    patterns = cfg.skip_files
    return [
        f
        for f in all_files
        if f.endswith(".md") and not any(fnmatch.fnmatchcase(os.path.basename(f), pat) for pat in patterns)
    ]


def inbox_pending(cfg: Config) -> list[str]:
    inbox = cfg.path(cfg.inbox_dir)
    if not inbox.is_dir():
        return []
    ignore = set(cfg.inbox_ignore)
    return sorted(f.name for f in inbox.iterdir() if f.is_file() and f.name not in ignore)


def uncovered(cfg: Config, all_files: list[str], registered_paths: set[str]) -> list[str]:
    """Covered-extension files with no registry entry (coverage gaps)."""
    exts = tuple(cfg.covered_ext)
    skip_names = set(cfg.coverage_skip) | {cfg.artifacts_file}
    return sorted(
        f
        for f in all_files
        if f.endswith(exts)
        and f not in registered_paths
        and os.path.basename(f) not in skip_names
        and f not in skip_names
    )
