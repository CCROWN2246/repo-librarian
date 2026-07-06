"""Load and validate `.librarian.toml`.

All policy that used to live as module constants in the original kb_index.py is
a config key here, with the original values as defaults. Unknown keys are hard
errors (exit 2 at the CLI layer) so typos surface instead of silently reverting
to defaults.
"""

from __future__ import annotations

import datetime
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = ".librarian.toml"

# Directories the scanner always excludes in addition to config skip_dirs
# ([paths] index/inbox/archive are appended at load time).
ALWAYS_SKIP = {".git", "__pycache__", ".ruff_cache", ".pytest_cache"}

DEFAULT_SKIP_DIRS = [
    ".git",
    ".claude",
    "tests",
    "node_modules",
    "__pycache__",
    "backups",
    ".venv",
    "venv",
]
DEFAULT_SKIP_FILES = ["CLAUDE.md", "AGENTS.md", "KNOWLEDGE_PROTOCOL.md"]
DEFAULT_COVERED_EXT = [".sql", ".py", ".json", ".sh", ".ipynb", ".csv", ".tsv", ".parquet", ".xlsx"]
DEFAULT_STATUSES = ["authoritative", "provisional", "draft", "reference", "retired", "archived"]
DEFAULT_AUTHORITIES = ["verified", "curated", "unverified"]
DEFAULT_REQUIRED_DOC = ["id", "title", "domain", "status", "last_verified"]
DEFAULT_REQUIRED_ART = ["id", "title", "domain", "status"]
DEFAULT_INBOX_IGNORE = ["README.md", ".gitkeep"]

FAIL_ON_CATEGORIES = {
    "missing_frontmatter",
    "unregistered",
    "orphans",
    "open_conflicts",
    "taxonomy",
    "fm_warnings",
}


class ConfigError(Exception):
    """Invalid or missing configuration; maps to exit code 2."""


@dataclass
class Source:
    name: str
    command: str | None = None  # template with {arg}
    skip_unless: str | None = None  # probe command; nonzero exit -> SKIP all checks of this source
    skip_if_unset: list[str] = field(default_factory=list)
    timeout: int | None = None


@dataclass
class Check:
    id: str
    kind: str  # assert | track
    doc: str
    cmd: str | None = None
    arg: str | None = None
    source: str = "local"
    extract: str = "scalar"
    expect: str | None = None
    timeout: int | None = None
    skip_if_unset: list[str] = field(default_factory=list)
    skip_unless: str | None = None


@dataclass
class Config:
    root: Path
    # paths
    index_dir: str = "_index"
    inbox_dir: str = "_inbox"
    archive_dir: str = "_archive"
    docs_dir: str = "."
    artifacts_file: str = "librarian-artifacts.toml"
    # scan
    skip_dirs: list[str] = field(default_factory=lambda: list(DEFAULT_SKIP_DIRS))
    skip_files: list[str] = field(default_factory=lambda: list(DEFAULT_SKIP_FILES))
    covered_ext: list[str] = field(default_factory=lambda: list(DEFAULT_COVERED_EXT))
    coverage_skip: list[str] = field(default_factory=list)
    inbox_ignore: list[str] = field(default_factory=lambda: list(DEFAULT_INBOX_IGNORE))
    # taxonomy
    domains: list[str] = field(default_factory=list)  # empty = free-form
    statuses: list[str] = field(default_factory=lambda: list(DEFAULT_STATUSES))
    authorities: list[str] = field(default_factory=lambda: list(DEFAULT_AUTHORITIES))
    required_doc_fields: list[str] = field(default_factory=lambda: list(DEFAULT_REQUIRED_DOC))
    required_artifact_fields: list[str] = field(default_factory=lambda: list(DEFAULT_REQUIRED_ART))
    # index
    absence_guard: bool = True
    absence_extra_patterns: list[str] = field(default_factory=list)
    fail_on: list[str] = field(default_factory=list)
    # warn when CATALOG.md's estimated token cost exceeds this (0 = off).
    # ~25 tokens/entry: 200 entries ≈ 7.5k tokens (fine), 500 ≈ 13k (the always-load
    # layer starts eating the budget it was built to protect).
    catalog_token_budget: int = 12000
    # verify
    stamp_docs: bool = False
    default_timeout: int = 60
    sources: dict[str, Source] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    # agent
    agent_claude: bool = True
    agent_agents_md: bool = True

    @property
    def all_skip_dirs(self) -> set[str]:
        return set(self.skip_dirs) | ALWAYS_SKIP | {self.index_dir, self.inbox_dir, self.archive_dir}

    def path(self, rel: str) -> Path:
        return self.root / rel


def today() -> datetime.date:
    """Injectable clock: LIBRARIAN_TODAY=YYYY-MM-DD overrides (golden tests)."""
    env = os.environ.get("LIBRARIAN_TODAY")
    if env:
        try:
            return datetime.date.fromisoformat(env)
        except ValueError as e:
            raise ConfigError(f"LIBRARIAN_TODAY={env!r} is not a valid YYYY-MM-DD date") from e
    return datetime.date.today()


def find_root(start: Path | None = None) -> Path | None:
    """Walk up from `start` (default cwd) to the first dir containing .librarian.toml."""
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / CONFIG_NAME).is_file():
            return candidate
    return None


def _expect_type(value, typ, where: str):
    if typ is list:
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ConfigError(f"{where}: expected a list of strings, got {value!r}")
    elif not isinstance(value, typ):
        raise ConfigError(f"{where}: expected {typ.__name__}, got {value!r}")
    return value


def _take(table: dict, where: str, spec: dict) -> dict:
    """Pop known keys (validating types); error on leftovers."""
    out = {}
    for key, typ in spec.items():
        if key in table:
            out[key] = _expect_type(table.pop(key), typ, f"{where}.{key}")
    if table:
        raise ConfigError(f"unknown key(s) in {where}: {', '.join(sorted(table))}")
    return out


def load(root: Path) -> Config:
    cfg_path = root / CONFIG_NAME
    if not cfg_path.is_file():
        raise ConfigError(f"no {CONFIG_NAME} found at {root} (run `librarian init` to create one)")
    try:
        with open(cfg_path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{cfg_path}: invalid TOML: {e}") from e

    cfg = Config(root=root)
    schema_version = data.pop("schema_version", 1)
    if schema_version != 1:
        raise ConfigError(f"unsupported schema_version {schema_version} (this librarian supports 1)")

    paths = _take(
        data.pop("paths", {}),
        "[paths]",
        {"index": str, "inbox": str, "archive": str, "docs": str, "artifacts": str},
    )
    cfg.index_dir = paths.get("index", cfg.index_dir)
    cfg.inbox_dir = paths.get("inbox", cfg.inbox_dir)
    cfg.archive_dir = paths.get("archive", cfg.archive_dir)
    cfg.docs_dir = paths.get("docs", cfg.docs_dir)
    cfg.artifacts_file = paths.get("artifacts", cfg.artifacts_file)

    scan = _take(
        data.pop("scan", {}),
        "[scan]",
        {
            "skip_dirs": list,
            "skip_files": list,
            "covered_ext": list,
            "coverage_skip": list,
            "inbox_ignore": list,
        },
    )
    for k in scan:
        setattr(cfg, k, scan[k])

    tax = _take(
        data.pop("taxonomy", {}),
        "[taxonomy]",
        {
            "domains": list,
            "statuses": list,
            "authorities": list,
            "required_doc_fields": list,
            "required_artifact_fields": list,
        },
    )
    for k in tax:
        setattr(cfg, k, tax[k])

    idx = _take(
        data.pop("index", {}),
        "[index]",
        {"absence_guard": bool, "absence_extra_patterns": list, "fail_on": list, "catalog_token_budget": int},
    )
    cfg.absence_guard = idx.get("absence_guard", cfg.absence_guard)
    cfg.absence_extra_patterns = idx.get("absence_extra_patterns", cfg.absence_extra_patterns)
    cfg.fail_on = idx.get("fail_on", cfg.fail_on)
    cfg.catalog_token_budget = idx.get("catalog_token_budget", cfg.catalog_token_budget)
    bad = set(cfg.fail_on) - FAIL_ON_CATEGORIES
    if bad:
        raise ConfigError(
            f"[index].fail_on: unknown categories {sorted(bad)} (valid: {sorted(FAIL_ON_CATEGORIES)})"
        )

    verify = data.pop("verify", {})
    if not isinstance(verify, dict):
        raise ConfigError("[verify]: expected a table")
    sources_tbl = verify.pop("sources", {})
    checks_list = verify.pop("checks", [])
    v = _take(verify, "[verify]", {"stamp_docs": bool, "default_timeout": int})
    cfg.stamp_docs = v.get("stamp_docs", cfg.stamp_docs)
    cfg.default_timeout = v.get("default_timeout", cfg.default_timeout)

    for name, tbl in sources_tbl.items():
        if not isinstance(tbl, dict):
            raise ConfigError(f"[verify.sources.{name}]: expected a table")
        s = _take(
            dict(tbl),
            f"[verify.sources.{name}]",
            {"command": str, "skip_unless": str, "skip_if_unset": list, "timeout": int},
        )
        cfg.sources[name] = Source(name=name, **s)

    if not isinstance(checks_list, list):
        raise ConfigError("[[verify.checks]]: expected an array of tables")
    seen_ids = set()
    for n, tbl in enumerate(checks_list, 1):
        if not isinstance(tbl, dict):
            raise ConfigError(f"[[verify.checks]] #{n}: expected a table")
        tbl = dict(tbl)
        if "layer" in tbl and "source" not in tbl:  # legacy alias
            tbl["source"] = tbl.pop("layer")
        where = f"[[verify.checks]] #{n} (id={tbl.get('id', '?')})"
        c = _take(
            tbl,
            where,
            {
                "id": str,
                "kind": str,
                "doc": str,
                "cmd": str,
                "arg": str,
                "source": str,
                "extract": str,
                "expect": str,
                "timeout": int,
                "skip_if_unset": list,
                "skip_unless": str,
            },
        )
        for req in ("id", "kind", "doc"):
            if req not in c:
                raise ConfigError(f"{where}: missing required field {req!r}")
        if c["kind"] not in ("assert", "track"):
            raise ConfigError(f"{where}: kind must be 'assert' or 'track', got {c['kind']!r}")
        if ("cmd" in c) == ("arg" in c):
            raise ConfigError(f"{where}: exactly one of 'cmd' or 'arg' is required")
        if c["kind"] == "assert" and "expect" not in c:
            raise ConfigError(f"{where}: assert checks require 'expect'")
        if c["id"] in seen_ids:
            raise ConfigError(f"{where}: duplicate check id {c['id']!r}")
        seen_ids.add(c["id"])
        check = Check(**c)
        if check.arg is not None:
            src = cfg.sources.get(check.source)
            if src is None or not src.command:
                raise ConfigError(f"{where}: uses 'arg' but source {check.source!r} has no command template")
        cfg.checks.append(check)

    agent = _take(data.pop("agent", {}), "[agent]", {"claude": bool, "agents_md": bool})
    cfg.agent_claude = agent.get("claude", cfg.agent_claude)
    cfg.agent_agents_md = agent.get("agents_md", cfg.agent_agents_md)

    if data:
        raise ConfigError(f"unknown top-level key(s) in {CONFIG_NAME}: {', '.join(sorted(data))}")
    return cfg
