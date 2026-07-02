"""The artifact registry: metadata for files that can't carry frontmatter.

`librarian-artifacts.toml` holds one `[[artifact]]` table per non-markdown
knowledge artifact (SQL, notebooks, exports, scripts). Entries are validated
individually with line-level errors — a malformed entry names itself instead of
silently dropping the whole registry (the failure mode of the old
registry-as-Python-import design).
"""

from __future__ import annotations

import tomllib

from .config import Config, ConfigError

REQUIRED = ("path", "id", "title", "domain", "kind", "status")
OPTIONAL = ("last_verified", "recheck", "read_when", "tags", "desc", "source_of_truth",
            "authority", "owner")


def load(cfg: Config) -> tuple[list[dict], list[str]]:
    """Return (artifacts, errors). Valid entries load even when siblings are broken."""
    path = cfg.path(cfg.artifacts_file)
    if not path.is_file():
        return [], []
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name}: invalid TOML: {e}") from e

    entries = data.pop("artifact", [])
    errors = [f"{path.name}: unknown top-level key(s): {', '.join(sorted(data))}"] if data else []
    if not isinstance(entries, list):
        raise ConfigError(f"{path.name}: expected [[artifact]] tables")

    artifacts: list[dict] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for n, e in enumerate(entries, 1):
        where = f"{path.name} [[artifact]] #{n} (id={e.get('id', '?')})"
        problems = [f"missing {k!r}" for k in REQUIRED if k not in e]
        problems += [f"unknown field {k!r}" for k in e if k not in REQUIRED + OPTIONAL]
        if e.get("authority") and e["authority"] not in cfg.authorities:
            problems.append(f"authority {e['authority']!r} not in {cfg.authorities}")
        if e.get("id") in seen_ids:
            problems.append(f"duplicate id {e['id']!r}")
        if e.get("path") in seen_paths:
            problems.append(f"duplicate path {e['path']!r}")
        if problems:
            errors.append(f"{where}: " + "; ".join(problems))
            continue
        seen_ids.add(e["id"])
        seen_paths.add(e["path"])
        artifacts.append(dict(e))
    return artifacts, errors


def to_toml_block(entry: dict) -> str:
    """Render one entry as a ready-to-paste [[artifact]] block (used by ingest)."""
    lines = ["[[artifact]]"]
    for k in REQUIRED + OPTIONAL:
        if k not in entry:
            continue
        v = entry[k]
        if isinstance(v, list):
            body = ", ".join(f'"{x}"' for x in v)
            lines.append(f"{k} = [{body}]")
        else:
            lines.append(f'{k} = "{v}"')
    return "\n".join(lines) + "\n"


REGISTRY_TEMPLATE = """# librarian-artifacts.toml — registry for non-markdown knowledge artifacts.
#
# .md docs carry YAML frontmatter; SQL, notebooks, data exports, and scripts can't,
# so they get an [[artifact]] entry here instead. `librarian index` lists any
# covered-extension file with no entry as a coverage gap.
#
# Fields: path, id, title, domain, kind, status (required);
#         last_verified, recheck, read_when, tags, desc, source_of_truth,
#         authority, owner (optional).
#
# [[artifact]]
# path = "queries/monthly_rollup.sql"
# id = "monthly-rollup-sql"
# title = "Monthly rollup query"
# domain = "data"
# kind = "sql"
# status = "authoritative"
# last_verified = "2026-01-31"
# read_when = ["compute the monthly rollup", "trace a rollup number"]
"""
