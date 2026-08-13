"""Wiring `verify` to your data — the drafting engine behind `add-check` and `connect`.

The verify ENGINE has always been capable (any shell command is a source), but reaching
it meant hand-writing TOML and knowing the `extract` spec. This module closes that gap by
DRAFTING checks: given a data file, it knows what is worth guarding (how many rows, what
columns) and emits a ready check whose `expect` is seeded from the live value.

Two invariants shape every draft:

- **The tool never writes the user's TOML.** `tomllib` is read-only (a documented config
  invariant), so drafts are `cmd`-based and self-contained — they need no `[verify.sources]`
  entry and land in the machine-owned `_index/generated-checks.json`, which `config.load`
  already merges. `to_toml()` exists only for the user who *wants* a hand-owned check.
- **A seeded `expect` is a claim, so it needs a human.** `add-check` gates an assert behind
  an explicit confirm; `connect` routes drafts through the propose->apply spine (the
  proposal review IS the gate). Neither ever freezes a live value unattended.

Pure + deterministic: drafting reads files and returns objects. Running the probe command
is the one side effect, and it lives in `probe()` so callers can draft without executing.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import backfill, extractors
from .config import Config

# Read only the head of a data file when sniffing its shape (headers, JSON kind).
MAX_SNIFF_BYTES = 64 * 1024

CSV_EXT = (".csv", ".tsv")

# Drafted commands are POSIX shell one-liners (awk/head/tr/sort), run the same way
# verify.py runs every check. Kept in sync with verify._run_cmd deliberately: a drafted
# check must execute identically to a hand-written one.
SHELL = "/bin/sh"

# Extensions we deliberately do not draft for, and the honest reason why. Reported
# rather than silently dropped: a scan that quietly covers less reads as full coverage.
SKIP_REASONS = {
    ".parquet": "binary — needs a CLI reader (duckdb/pqrs); see docs/verify-recipes.md",
    ".xlsx": "binary — needs a CLI reader; see docs/verify-recipes.md",
    ".db": "sqlite — wire it by hand (one check per table); see docs/verify-recipes.md",
    ".sqlite": "sqlite — wire it by hand (one check per table); see docs/verify-recipes.md",
    ".sqlite3": "sqlite — wire it by hand (one check per table); see docs/verify-recipes.md",
}


class CheckDraftError(Exception):
    """A draft could not be built (bad intent, unreadable file, unknown column)."""


@dataclass
class CheckDraft:
    """One drafted verify check, before it is written anywhere."""

    id: str
    kind: str  # assert | track
    doc: str
    cmd: str
    extract: str
    expect: str | None = None
    intent: str = ""  # human label: what this check guards
    origin: str = ""  # the data file it was drafted from ("" for a raw --cmd)
    live: str | None = None  # what the command returned when drafted (display only; never serialized)

    def to_sidecar(self) -> dict:
        """The `generated-checks.json` entry (what `config.load` merges into cfg.checks)."""
        out = {
            "id": self.id,
            "kind": self.kind,
            "doc": self.doc,
            "cmd": self.cmd,
            "extract": self.extract,
        }
        if self.kind == "assert":
            out["expect"] = self.expect or ""
        return out

    def to_toml(self) -> str:
        """A hand-owned `[[verify.checks]]` block, for a user who'd rather own it in TOML."""

        def q(v: str) -> str:
            return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'

        lines = [
            "[[verify.checks]]",
            f"id      = {q(self.id)}",
            f"kind    = {q(self.kind)}",
            f"doc     = {q(self.doc)}",
            f"cmd     = {q(self.cmd)}",
            f"extract = {q(self.extract)}",
        ]
        if self.kind == "assert":
            lines.append(f"expect  = {q(self.expect or '')}")
        return "\n".join(lines) + "\n"

    def to_partial(self, *, rationale: str) -> dict:
        """An `add_check` proposal partial for `proposals.build_from_partial`.

        The target is the doc the check guards — that is the file whose claim gains a
        guard, and it gives apply a real base_sha256 to hash.
        """
        return {
            "type": "add_check",
            "targets": [{"path": self.doc}],
            "action": {"check_id": self.id, "check": self.to_sidecar()},
            "rationale": rationale,
            "provenance": {
                "source": self.origin or "local",
                "command": self.cmd,
                "evidence": self.expect if self.kind == "assert" else "",
            },
        }


# --- sniffing a data file ------------------------------------------------------


def _head_text(path: Path) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(MAX_SNIFF_BYTES)
    except OSError as e:
        raise CheckDraftError(f"cannot read {path.name}: {e}") from e


def separator(rel: str) -> str:
    return "\t" if rel.lower().endswith(".tsv") else ","


def header_columns(cfg: Config, rel: str) -> list[str]:
    """Column names from a CSV/TSV header row. Empty list if the file has no rows."""
    text = _head_text(cfg.path(rel))
    for line in text.splitlines():
        if line.strip():
            sep = separator(rel)
            return [c.strip().strip('"').strip() for c in line.rstrip("\r").split(sep)]
    return []


def json_kind(cfg: Config, rel: str) -> str:
    """'array' | 'object' | 'other' — what a .json file holds at the top level.

    Sniffs the head only, so a large-but-truncated file falls back to the first
    non-whitespace character rather than claiming the JSON is malformed.
    """
    text = _head_text(cfg.path(rel))
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        stripped = text.lstrip()
        if stripped.startswith("["):
            return "array"
        if stripped.startswith("{"):
            return "object"
        return "other"
    if isinstance(data, list):
        return "array"
    if isinstance(data, dict):
        return "object"
    return "other"


# --- the command templates -----------------------------------------------------


def rows_cmd(rel: str) -> str:
    """Data-row count (header excluded).

    `awk END{NR}` rather than `tail -n +2 | wc -l`: awk counts a final line that has no
    trailing newline, which `wc -l` silently drops — an off-by-one in a number the whole
    point of this tool is to get right. The guard keeps an empty file at 0, not -1.

    The ternary MUST stay parenthesized: bare `print NR > 0 ? ...` parses as a redirection
    of `print NR` into a file named "0", which is a syntax error at best and a stray file
    at worst.
    """
    return "awk 'END {print (NR > 0 ? NR - 1 : 0)}' " + shlex.quote(rel)


def schema_cmd(rel: str) -> str:
    """The header row, normalized to a single comparable line.

    `tr -d '\\r'` so a CRLF file doesn't drift against a LF-authored expect; TSV headers
    are comma-joined because the `scalar` extractor tab-splits and would otherwise keep
    only the last column.
    """
    base = "head -n 1 " + shlex.quote(rel) + " | tr -d '\\r'"
    return base + " | tr '\\t' ','" if rel.lower().endswith(".tsv") else base


def distinct_cmd(rel: str, column: str, columns: list[str]) -> str:
    """Count of distinct values in one column (header excluded)."""
    try:
        idx = columns.index(column) + 1
    except ValueError:
        known = ", ".join(columns) or "(no header row)"
        raise CheckDraftError(f"{rel}: no column named {column!r} (columns: {known})") from None
    sep = "\\t" if rel.lower().endswith(".tsv") else ","
    return f"awk -F'{sep}' 'NR > 1 {{print ${idx}}}' " + shlex.quote(rel) + " | sort -u | grep -c . || true"


def length_cmd(rel: str) -> str:
    """Emit a JSON document for the `json:` extractor to walk."""
    return "cat " + shlex.quote(rel)


# --- drafting ------------------------------------------------------------------


def draft_id(rel: str, intent: str) -> str:
    """Stable, readable check id: <path-slug>-<intent>."""
    stem = backfill.slug(rel.replace(".", "-"))
    return f"{stem}-{backfill.slug(intent)}"


def draft(
    cfg: Config,
    rel: str,
    intent: str,
    *,
    doc: str,
    check_id: str | None = None,
) -> CheckDraft:
    """Build one draft for `rel` under `intent` (rows | schema | distinct:<col> | length).

    Seeds shape from the file but NOT `expect` — that needs a live run (`probe`), because
    the expected value must be what the command actually returns, not what we predict.
    """
    if intent == "rows":
        cmd, extract, kind = rows_cmd(rel), "scalar", "track"
    elif intent == "schema":
        cmd, extract, kind = schema_cmd(rel), "scalar", "assert"
    elif intent == "length":
        cmd, extract, kind = length_cmd(rel), "json:length", "track"
    elif intent.startswith("distinct:"):
        column = intent[len("distinct:") :]
        if not column:
            raise CheckDraftError("distinct: needs a column name, e.g. distinct:customer_id")
        cmd = distinct_cmd(rel, column, header_columns(cfg, rel))
        extract, kind = "scalar", "assert"
    else:
        raise CheckDraftError(f"unknown intent {intent!r} (valid: rows, schema, length, distinct:<column>)")
    return CheckDraft(
        id=check_id or draft_id(rel, intent),
        kind=kind,
        doc=doc,
        cmd=cmd,
        extract=extract,
        intent=intent,
        origin=rel,
    )


def drafts_for_file(cfg: Config, rel: str, *, doc: str, schema: bool = True) -> list[CheckDraft]:
    """Every check worth drafting for one data file. Empty list = nothing to draft.

    Callers get the reason from `skip_reason` — this returns [] rather than raising so a
    bulk scan can report a mixed result instead of aborting on the first odd file.
    """
    low = rel.lower()
    if low.endswith(CSV_EXT):
        if not header_columns(cfg, rel):
            return []  # no header row => nothing to count rows against; see skip_reason
        out = [draft(cfg, rel, "rows", doc=doc)]
        if schema:
            out.append(draft(cfg, rel, "schema", doc=doc))
        return out
    if low.endswith(".json") and json_kind(cfg, rel) == "array":
        return [draft(cfg, rel, "length", doc=doc)]
    return []


def skip_reason(cfg: Config, rel: str) -> str | None:
    """Why `rel` yields no drafts, or None if it does yield some."""
    low = rel.lower()
    ext = "." + low.rsplit(".", 1)[-1] if "." in low else ""
    if ext in SKIP_REASONS:
        return SKIP_REASONS[ext]
    if low.endswith(CSV_EXT):
        return None if header_columns(cfg, rel) else "empty file — no header row to guard"
    if low.endswith(".json"):
        kind = json_kind(cfg, rel)
        if kind == "array":
            return None
        return f"top-level JSON {kind} — no row/length to count; wire a `json:<path>` check by hand"
    return f"no drafting rule for {ext or 'this file type'} — see docs/verify-recipes.md"


def scan(cfg: Config, rel_dir: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Walk `rel_dir` for data files. Returns (draftable_paths, [(path, skip_reason)]).

    Both lists are path-sorted for determinism. Directories the scanner always excludes
    (`.git`, `_index`, ...) are honoured so a `connect .` never drafts against our own state.
    """
    root = cfg.path(rel_dir)
    draftable: list[str] = []
    skipped: list[tuple[str, str]] = []
    skip_dirs = cfg.all_skip_dirs
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(cfg.root).as_posix()
        except ValueError:
            continue  # outside the repo (symlink) — never draft for it
        if any(part in skip_dirs for part in path.relative_to(cfg.root).parts[:-1]):
            continue
        if path.suffix.lower() not in cfg.covered_ext:
            continue
        reason = skip_reason(cfg, rel)
        if reason is None:
            draftable.append(rel)
        else:
            skipped.append((rel, reason))
    return draftable, skipped


# --- attribution: which doc does a check belong to? ----------------------------


def attribute_doc(cfg: Config, rel: str, items: list[dict]) -> str | None:
    """The catalogued .md doc that cites `rel`, if exactly one does.

    A check's `doc` is what gets NAMED when the value drifts, so it must be the doc making
    the claim — not the data file. An exact path/basename mention is used rather than the
    fuzzy ranker: a wrong attribution sends the reader to the wrong file, so ambiguity
    (zero matches, or several) returns None and the caller asks the human.
    """
    basename = rel.rsplit("/", 1)[-1]
    hits = []
    for item in sorted(items, key=lambda d: str(d.get("path", ""))):
        path = str(item.get("path", ""))
        if item.get("kind") != "doc" or not path.endswith(".md"):
            continue
        try:
            body = cfg.path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if rel in body or basename in body:
            hits.append(path)
    return hits[0] if len(hits) == 1 else None


# --- running the probe ---------------------------------------------------------


def probe(cfg: Config, cmd: str, extract: str, *, timeout: int | None = None) -> str:
    """Run a drafted command ONCE and return its extracted value.

    This is the "show me the live value before you freeze it" step. Every failure mode is
    raised as CheckDraftError so the caller reports the real cause (a wrong command, a
    missing CLI) instead of silently writing a check that can never pass.
    """
    limit = timeout or cfg.default_timeout
    if not Path(SHELL).exists():
        # verify has always shelled out through /bin/sh; drafting inherits that. Say so
        # plainly instead of surfacing a bare "[WinError 2] cannot find the file".
        raise CheckDraftError(
            f"no POSIX shell at {SHELL} — `verify` (and therefore check drafting) shells out "
            "through it. On Windows, run the librarian from WSL or Git Bash."
        )
    try:
        proc = subprocess.run(
            [SHELL, "-c", cmd],
            cwd=cfg.root,
            timeout=limit,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as e:
        raise CheckDraftError(f"command timed out after {limit}s: {cmd}") from e
    except OSError as e:
        raise CheckDraftError(f"cannot run command: {e}") from e
    if proc.returncode != 0 and extract != "exit_code":
        detail = (proc.stderr.strip() or proc.stdout.strip())[:300]
        raise CheckDraftError(f"command exited {proc.returncode}: {detail}")
    try:
        return extractors.extract(extract, proc.stdout, proc.returncode)
    except extractors.ExtractError as e:
        raise CheckDraftError(f"cannot extract a value ({e}) — check the `extract` spec") from e
