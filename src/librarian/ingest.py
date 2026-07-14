"""Inbox triage: list pending uploads, stamp frontmatter, file them into the repo.

The intake lifecycle: a raw file lands in the inbox -> assign an authority tier
from its provenance (non-technical transcript = unverified; written with
direct/technical access = curated) -> classify (domain + read_when) -> file it.
Interactive prompts have flag equivalents so agents can run non-interactively.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import backfill, frontmatter, registry
from .config import Config


@dataclass
class IngestResult:
    moved_to: str
    frontmatter_added: bool
    artifact_block: str | None = None  # for non-.md files: paste into the registry
    preview: str | None = None  # --dry-run: the .md content that WOULD be written


def pending(cfg: Config) -> list[str]:
    from . import scanner

    return scanner.inbox_pending(cfg)


def ingest_file(
    cfg: Config,
    name: str,
    *,
    domain: str,
    status: str,
    authority: str | None,
    dest: str,
    recheck: str,
    today: date,
    read_when: list[str] | None = None,
    owner: str = "",
    dry_run: bool = False,
) -> IngestResult:
    src = cfg.path(cfg.inbox_dir) / name
    if not src.is_file():
        raise FileNotFoundError(f"{cfg.inbox_dir}/{name} not found")
    # --dest is a DIRECTORY by design (the filename is appended). A path that looks
    # like a file (.md suffix) is almost always a mistake; fail loud instead of
    # silently creating a directory literally named "foo.md".
    if dest.endswith(".md"):
        raise ValueError(
            f"--dest must be a directory (it auto-names the file); "
            f"pass '{str(Path(dest).parent) or '.'}/', not '{dest}'"
        )
    dest_dir = cfg.path(dest)
    target = dest_dir / name
    if target.exists():
        raise FileExistsError(f"{target} already exists — resolve manually")

    rel = str(Path(dest) / name).replace("\\", "/")
    if name.endswith(".md"):
        text = src.read_text(encoding="utf-8", errors="replace")
        added = False
        if frontmatter.find_block(text) is None:
            meta = {
                "id": backfill.slug(rel),
                "title": backfill.title_of(text, name),
                "domain": domain,
                "status": status,
            }
            if authority:
                meta["authority"] = authority
            meta.update(
                last_verified=today.isoformat(),
                recheck=recheck,
                read_when=read_when or [],
                owner=owner,
                tags=[],
            )
            text = frontmatter.serialize(meta) + text
            added = True
        else:
            # Respect existing frontmatter but make sure the tier is recorded.
            if authority:
                text = frontmatter.set_field(text, "authority", authority)
        if dry_run:
            return IngestResult(moved_to=rel, frontmatter_added=added, preview=text)
        dest_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        src.unlink()
        return IngestResult(moved_to=rel, frontmatter_added=added)

    # Non-.md: move it and emit a ready-to-paste registry block.
    if dry_run:
        entry = {
            "path": rel,
            "id": backfill.slug(rel.replace(".", "-")),
            "title": name,
            "domain": domain,
            "kind": (src.suffix.lstrip(".") or "file"),
            "status": status,
            "last_verified": today.isoformat(),
        }
        if authority:
            entry["authority"] = authority
        if read_when:
            entry["read_when"] = read_when
        return IngestResult(
            moved_to=rel, frontmatter_added=False, artifact_block=registry.to_toml_block(entry)
        )
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(target))
    entry = {
        "path": rel,
        "id": backfill.slug(rel.replace(".", "-")),
        "title": name,
        "domain": domain,
        "kind": (src.suffix.lstrip(".") or "file"),
        "status": status,
        "last_verified": today.isoformat(),
    }
    if authority:
        entry["authority"] = authority
    if read_when:
        entry["read_when"] = read_when
    return IngestResult(moved_to=rel, frontmatter_added=False, artifact_block=registry.to_toml_block(entry))
