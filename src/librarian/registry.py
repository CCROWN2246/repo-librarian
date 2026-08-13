"""The artifact registry: metadata for files that can't carry frontmatter.

`librarian-artifacts.toml` holds one `[[artifact]]` table per non-markdown
knowledge artifact (SQL, notebooks, exports, scripts). Entries are validated
individually with line-level errors — a malformed entry names itself instead of
silently dropping the whole registry (the failure mode of the old
registry-as-Python-import design).
"""

from __future__ import annotations

import json
import tomllib

from .config import Config, ConfigError

REQUIRED = ("path", "id", "title", "domain", "kind", "status")
OPTIONAL = ("last_verified", "recheck", "read_when", "tags", "desc", "source_of_truth", "authority", "owner")

# Machine-authored artifact metadata, keyed by path. This is how the librarian indexes a
# file that cannot carry frontmatter (SQL, CSV, notebooks) — the class that most needs
# machine-written routing and, before this existed, was the one class where it was
# structurally impossible (`set_read_when` could only touch frontmatter, so every artifact
# proposal returned STALE and the dream agent re-proposed it forever).
GENERATED_FILE = "generated-artifacts.json"


def load_generated(cfg: Config) -> list[dict]:
    """Machine-authored artifact entries/overlays. Tolerant: a corrupt sidecar must not
    brick every command that reads the registry (mirrors the generated-checks loader)."""
    path = cfg.path(cfg.index_dir) / GENERATED_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict) and isinstance(e.get("path"), str) and e.get("path")]


def save_generated(cfg: Config, entries: list[dict]) -> None:
    out = cfg.path(cfg.index_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = sorted(entries, key=lambda e: str(e.get("path", "")))
    (out / GENERATED_FILE).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def upsert_generated(cfg: Config, path: str, fields: dict) -> None:
    """Merge `fields` into the machine overlay for `path` (create it if absent)."""
    entries = load_generated(cfg)
    for e in entries:
        if e.get("path") == path:
            e.update(fields)
            break
    else:
        entries.append({"path": path, **fields})
    save_generated(cfg, entries)


def _is_empty(value) -> bool:
    """A field the human left for the machine to fill: absent, blank, or a TODO placeholder."""
    if value is None or value == "" or value == []:
        return True
    if isinstance(value, list):
        return all(not str(x).strip() or "todo" in str(x).lower() for x in value)
    return "todo" in str(value).lower()


def load(cfg: Config) -> tuple[list[dict], list[str]]:
    """Return (artifacts, errors). Valid entries load even when siblings are broken."""
    path = cfg.path(cfg.artifacts_file)
    if not path.is_file():
        # No hand-authored registry is the AI-indexes-everything case, not the empty case:
        # machine-authored entries must still load, or a repo where the human never wrote
        # TOML would have no artifacts at all.
        return _merge_generated(cfg, [], set())
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

    artifacts, gen_errors = _merge_generated(cfg, artifacts, seen_ids)
    return artifacts, errors + gen_errors


def _merge_generated(cfg: Config, artifacts: list[dict], seen_ids: set[str]) -> tuple[list[dict], list[str]]:
    """Layer machine-authored metadata over the hand-authored registry.

    One rule, both cases: **the machine fills gaps and never overwrites human intent.**
    - An overlay for a path that HAS an `[[artifact]]` entry fills only the fields the human
      left empty or marked TODO (`read_when = []  # TODO` is the canonical case).
    - An overlay for a path with no entry stands alone, and must carry the required fields.

    That rule is why this can't silently shadow anything: a human value always wins, so
    there is no precedence surprise to diagnose later.
    """
    by_path = {a["path"]: a for a in artifacts}
    errors: list[str] = []
    for gen in load_generated(cfg):
        path = gen["path"]
        fields = {k: v for k, v in gen.items() if k != "path"}
        existing = by_path.get(path)
        if existing is not None:
            filled = [k for k, v in fields.items() if k in REQUIRED + OPTIONAL and _is_empty(existing.get(k))]
            for k in filled:
                existing[k] = fields[k]
            if filled:
                existing["_generated_fields"] = sorted(set(existing.get("_generated_fields", []) + filled))
            continue
        entry = {"path": path, **fields}
        # "Provisional propagates." A wholly machine-authored entry has never been seen by a
        # human, so it enters at the lowest trust tier and STALENESS surfaces it for review.
        # An overlay that merely FILLS a gap on a human's entry does not downgrade it — the
        # doc's authority is about its content, and `_generated_fields` already records which
        # individual fields the machine wrote.
        entry.setdefault("authority", "unverified")
        problems = [f"missing {k!r}" for k in REQUIRED if k not in entry]
        if entry["authority"] not in cfg.authorities:
            problems.append(f"authority {entry['authority']!r} not in {cfg.authorities}")
        if entry.get("id") in seen_ids:
            problems.append(f"duplicate id {entry.get('id')!r}")
        if problems:
            errors.append(f"{GENERATED_FILE} (path={path}): " + "; ".join(problems))
            continue
        seen_ids.add(entry["id"])
        entry["_generated_fields"] = sorted(k for k in fields if k in REQUIRED + OPTIONAL)
        artifacts.append(entry)
        by_path[path] = entry
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
