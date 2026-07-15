"""`librarian suggest` — auto-draft registry entries for uncovered artifacts.

Turns the coverage backlog ("N code/data files need a registry entry") into
ready-to-paste `[[artifact]]` TOML by harvesting each file's own self-description:
a SQL leading comment, a Python module docstring, a notebook's first markdown
cell, a CSV header row. Drafts are a starting point, not a verdict — `read_when`
is left as a TODO because routing phrases are the one thing only a human (or an
agent that understands the project) can write well.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import backfill
from .catalog import CatalogResult
from .config import Config

MAX_READ_BYTES = 64 * 1024  # harvest from the head of large files only

KIND_BY_EXT = {
    ".sql": "sql",
    ".py": "script",
    ".sh": "script",
    ".ipynb": "notebook",
    ".json": "json",
    ".csv": "csv",
    ".tsv": "csv",
    ".parquet": "data",
    ".xlsx": "data",
}


@dataclass
class Suggestion:
    path: str
    id: str
    title: str
    kind: str
    desc: str | None = None


def _head(path: Path) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(MAX_READ_BYTES)
    except OSError:
        return ""


def _comment_lines(text: str, marker: str) -> list[str]:
    """Leading comment lines (skipping shebangs/blank lines), markers stripped."""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#!"):
            if out:
                break
            continue
        if stripped.startswith(marker):
            body = stripped[len(marker) :].strip().lstrip("-=# ").strip()
            if body:
                out.append(body)
        else:
            break
    return out


def _harvest_sql(text: str) -> tuple[str | None, str | None]:
    lines = _comment_lines(text, "--")
    if not lines:
        return None, None
    return lines[0], (" ".join(lines[1:3]) or None)


def _harvest_sh(text: str) -> tuple[str | None, str | None]:
    lines = _comment_lines(text, "#")
    if not lines:
        return None, None
    return lines[0], (" ".join(lines[1:3]) or None)


def _harvest_py(text: str) -> tuple[str | None, str | None]:
    try:
        doc = ast.get_docstring(ast.parse(text))
    except SyntaxError:
        doc = None
    if not doc:
        return _harvest_sh(text)  # fall back to leading # comments
    lines = [ln.strip() for ln in doc.strip().splitlines() if ln.strip()]
    title = lines[0].rstrip(".") if lines else None
    return title, (" ".join(lines[1:3]) or None)


def _harvest_ipynb(text: str) -> tuple[str | None, str | None]:
    try:
        nb = json.loads(text)
        cells = nb.get("cells", []) if isinstance(nb, dict) else []
        for cell in cells:
            if isinstance(cell, dict) and cell.get("cell_type") == "markdown":
                src = "".join(cell.get("source", []))
                m = re.search(r"^#+\s+(.+)$", src, re.MULTILINE)
                first = m.group(1).strip() if m else src.strip().splitlines()[0].strip()
                return (first or None), None
    except (json.JSONDecodeError, IndexError):
        pass
    return None, None


def _harvest_csv(text: str) -> tuple[str | None, str | None]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None, None
    sep = "\t" if "\t" in lines[0] else ","
    cols = [c.strip().strip('"') for c in lines[0].split(sep) if c.strip()]
    if not cols:
        return None, None
    shown = ", ".join(cols[:12]) + ("…" if len(cols) > 12 else "")
    # data-row count is approximate for large files (we read only the head)
    n = len(lines) - 1
    approx = "~" if len(text) >= MAX_READ_BYTES else ""
    return None, f"columns: {shown} ({approx}{n} data rows)"


def _harvest_json(text: str) -> tuple[str | None, str | None]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None, None
    if isinstance(data, dict) and data:
        keys = sorted(data)[:10]
        return None, "top-level keys: " + ", ".join(keys) + ("…" if len(data) > 10 else "")
    if isinstance(data, list):
        return None, f"array of {len(data)} items"
    return None, None


def harvest(path: Path, rel: str) -> Suggestion:
    ext = path.suffix.lower()
    kind = KIND_BY_EXT.get(ext, ext.lstrip(".") or "file")
    title = desc = None
    if ext in (".parquet", ".xlsx"):
        pass  # binary — nothing to harvest safely with stdlib
    else:
        text = _head(path)
        if ext == ".sql":
            title, desc = _harvest_sql(text)
        elif ext == ".py":
            title, desc = _harvest_py(text)
        elif ext == ".sh":
            title, desc = _harvest_sh(text)
        elif ext == ".ipynb":
            title, desc = _harvest_ipynb(text)
        elif ext in (".csv", ".tsv"):
            title, desc = _harvest_csv(text)
        elif ext == ".json":
            title, desc = _harvest_json(text)
    if not title:
        base = re.sub(rf"{re.escape(ext)}$", "", path.name).replace("-", " ").replace("_", " ")
        title = base.strip().title() or path.name
    if len(title) > 90:
        title = title[:87] + "…"
    return Suggestion(
        path=rel,
        id=backfill.slug(rel.replace(".", "-")) or "artifact",
        title=title,
        kind=kind,
        desc=desc,
    )


def build_suggestions(cfg: Config, res: CatalogResult) -> list[Suggestion]:
    return [harvest(cfg.path(rel), rel) for rel in sorted(res.uncovered)]


def to_toml(s: Suggestion, today: date, *, domain: str = "uncategorized") -> str:
    def q(v: str) -> str:
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'

    lines = [
        "[[artifact]]",
        f"path = {q(s.path)}",
        f"id = {q(s.id)}",
        f"title = {q(s.title)}",
        f"domain = {q(domain)}",
        f"kind = {q(s.kind)}",
        'status = "reference"',
        f'last_verified = "{today.isoformat()}"',
        "read_when = []  # TODO: task phrases — when should the agent open this?",
    ]
    if s.desc:
        lines.append(f"desc = {q(s.desc)}")
    return "\n".join(lines) + "\n"


def append_to_registry(cfg: Config, blocks: list[str]) -> Path:
    reg = cfg.path(cfg.artifacts_file)
    existing = reg.read_text(encoding="utf-8") if reg.exists() else ""
    sep = "" if (not existing or existing.endswith("\n\n")) else ("\n" if existing.endswith("\n") else "\n\n")
    header = "# --- drafted by `librarian suggest` — review each: set domain/status, write read_when ---\n"
    reg.write_text(existing + sep + header + "\n".join(blocks), encoding="utf-8")
    return reg
