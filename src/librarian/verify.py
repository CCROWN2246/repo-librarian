"""The verify engine: fact-check doc claims against their live sources.

Each check runs a shell command and compares the extracted output against an
expected value (`assert` — mismatch is DRIFT and fails the run) or a tracked
baseline (`track` — a change is CHANGED and only warns; the value legitimately
moves). This is what makes the `verified` authority tier real: a stale number
becomes a red line in CI instead of a wrong number in a deliverable.

SKIP contract: a check (or its source) can declare `skip_if_unset` env vars or
a `skip_unless` probe command; and any check command that exits with code 3
reports SKIP rather than ERROR. Skipped checks keep the run green — checks
against a source you haven't connected yet activate automatically when you do.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import extractors, frontmatter
from .config import Check, Config, Source

SKIP_EXIT_CODE = 3
BASELINES_FILE = "baselines.json"
PROVENANCE_FILE = "provenance.json"
PROVENANCE_SCHEMA = 1
LAST_VERIFIED_FILE = ".last_verified"

STATUS_ORDER = ["DRIFT", "ERROR", "CHANGED", "NEW", "SKIP", "PASS", "OK"]


@dataclass
class CheckResult:
    id: str
    kind: str
    doc: str
    source: str
    status: str  # PASS DRIFT OK CHANGED NEW SKIP ERROR
    live: str | None = None
    expect: str | None = None
    baseline: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class RunResult:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(r.status in ("DRIFT", "ERROR") for r in self.results)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.results:
            out[r.status] = out.get(r.status, 0) + 1
        return out


class _Skip(Exception):
    pass


def _run_cmd(cmd: str, cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/sh", "-c", cmd], cwd=cwd, timeout=timeout, capture_output=True, text=True)


def _check_skips(
    check: Check, source: Source | None, cwd: Path, timeout: int, probe_cache: dict[str, bool]
) -> None:
    """Raise _Skip if any skip condition applies (env vars, then probe commands)."""
    unset = [
        v for v in (check.skip_if_unset + (source.skip_if_unset if source else [])) if not os.environ.get(v)
    ]
    if unset:
        raise _Skip(f"env not set: {', '.join(unset)}")
    for probe in filter(None, [check.skip_unless, source.skip_unless if source else None]):
        if probe not in probe_cache:
            try:
                probe_cache[probe] = _run_cmd(probe, cwd, timeout).returncode == 0
            except (subprocess.TimeoutExpired, OSError):
                probe_cache[probe] = False
        if not probe_cache[probe]:
            raise _Skip(f"probe failed: {probe}")


def _resolve_cmd(check: Check, source: Source | None) -> str:
    if check.cmd is not None:
        return check.cmd
    assert check.arg is not None and source is not None and source.command
    return source.command.replace("{arg}", shlex.quote(check.arg))


def load_baselines(cfg: Config) -> dict:
    path = cfg.path(cfg.index_dir) / BASELINES_FILE
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_baselines(cfg: Config, baselines: dict) -> None:
    out = cfg.path(cfg.index_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / BASELINES_FILE).write_text(
        json.dumps(baselines, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run(
    cfg: Config, *, only_source: str | None = None, only_id: str | None = None, only_kind: str | None = None
) -> RunResult:
    baselines = load_baselines(cfg)
    probe_cache: dict[str, bool] = {}
    out = RunResult()
    for check in cfg.checks:
        if only_source and check.source != only_source:
            continue
        if only_id and not fnmatch.fnmatch(check.id, only_id):
            continue
        if only_kind and check.kind != only_kind:
            continue
        source = cfg.sources.get(check.source)
        timeout = check.timeout or (source.timeout if source else None) or cfg.default_timeout
        rec = CheckResult(id=check.id, kind=check.kind, doc=check.doc, source=check.source, status="ERROR")
        try:
            _check_skips(check, source, cfg.root, timeout, probe_cache)
            cmd = _resolve_cmd(check, source)
            proc = _run_cmd(cmd, cfg.root, timeout)
            if proc.returncode == SKIP_EXIT_CODE:
                raise _Skip(
                    f"command exited {SKIP_EXIT_CODE} (SKIP contract)"
                    + (f": {proc.stderr.strip()[:200]}" if proc.stderr.strip() else "")
                )
            if proc.returncode != 0 and check.extract != "exit_code":
                raise RuntimeError(
                    f"command exited {proc.returncode}: {(proc.stderr.strip() or proc.stdout.strip())[:300]}"
                )
            live = extractors.extract(check.extract, proc.stdout, proc.returncode)
            rec.live = live
            if check.kind == "assert":
                rec.expect = check.expect
                rec.status = "PASS" if live == check.expect else "DRIFT"
            else:
                base = baselines.get(check.id, {}).get("value")
                rec.baseline = base
                if base is None:
                    rec.status = "NEW"
                else:
                    rec.status = "OK" if live == base else "CHANGED"
        except _Skip as e:
            rec.status = "SKIP"
            rec.error = str(e)
        except subprocess.TimeoutExpired:
            rec.status = "ERROR"
            rec.error = f"timed out after {timeout}s"
        except (RuntimeError, OSError, extractors.ExtractError) as e:
            rec.status = "ERROR"
            rec.error = str(e)
        out.results.append(rec)
    return out


def update_baselines(cfg: Config, run_result: RunResult, today: date) -> list[str]:
    """Record NEW/CHANGED track values; prune baselines with no matching check.

    Returns a list of human-readable actions taken.
    """
    baselines = load_baselines(cfg)
    actions = []
    for r in run_result.results:
        if r.kind == "track" and r.status in ("NEW", "CHANGED") and r.live is not None:
            old = baselines.get(r.id, {}).get("value")
            baselines[r.id] = {"value": r.live, "recorded": today.isoformat()}
            actions.append(
                f"{r.id}: baseline {old!r} -> {r.live!r}"
                if old is not None
                else f"{r.id}: baseline recorded {r.live!r}"
            )
    known = {c.id for c in cfg.checks}
    for orphan in sorted(set(baselines) - known):
        del baselines[orphan]
        actions.append(f"{orphan}: pruned (no matching check)")
    if actions:
        save_baselines(cfg, baselines)
    return actions


def load_provenance(cfg: Config) -> dict:
    """The persisted provenance chain, keyed by check_id. Feeds `librarian why`,
    MCP sourced answers, and enrichment labels (E2/E3/E1/B5). Missing -> {}."""
    path = cfg.path(cfg.index_dir) / PROVENANCE_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {r["check_id"]: r for r in data.get("records", []) if isinstance(r, dict) and r.get("check_id")}


def save_provenance(cfg: Config, records: dict) -> None:
    out = cfg.path(cfg.index_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": PROVENANCE_SCHEMA,
        "records": [records[k] for k in sorted(records)],
    }
    # sort_keys like baselines.json -> stable, minimal-diff serialization (committed file).
    (out / PROVENANCE_FILE).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_provenance(cfg: Config, run_result: RunResult, today: date) -> None:
    """Persist one provenance record per non-SKIP check (fact -> command/source/value/
    timestamp). MERGES: only check_ids present in this run are refreshed, so a filtered
    `verify --source X` never wipes other sources. Orphaned records are pruned."""
    records = load_provenance(cfg)
    by_id = {c.id: c for c in cfg.checks}
    for r in run_result.results:
        if r.status == "SKIP":
            continue
        check = by_id.get(r.id)
        source = cfg.sources.get(check.source) if check else None
        try:
            command = _resolve_cmd(check, source) if check else None
        except (AssertionError, AttributeError):
            command = None
        rec = {
            "check_id": r.id,
            "doc": r.doc,
            "source": r.source,
            "kind": r.kind,
            "command": command,
            "live": r.live,
            "baseline": r.baseline,
            "expect": r.expect,
            "status": r.status,
            "verified_at": today.isoformat(),
        }
        records[r.id] = {k: v for k, v in rec.items() if v is not None}
    for orphan in set(records) - set(by_id):
        del records[orphan]
    save_provenance(cfg, records)


def failing_checks(cfg: Config) -> list[dict]:
    """Registered checks currently DRIFT/ERROR per the LAST persisted verify run
    (provenance.json). Pull-only and cheap — never re-runs a check. This is what lets the
    greeting / dream surface a failing check without recomputing every source (item 2)."""
    out = []
    for cid, r in load_provenance(cfg).items():
        if r.get("status") in ("DRIFT", "ERROR"):
            out.append(
                {
                    "id": cid,
                    "doc": r.get("doc", ""),
                    "status": r.get("status"),
                    "expect": r.get("expect"),
                    "live": r.get("live"),
                    "verified_at": r.get("verified_at"),
                }
            )
    out.sort(key=lambda x: x["id"])
    return out


def accept_expect(cfg: Config, check_id: str, live: str) -> bool:
    """Update a generated (add_check) assert check's `expect` to `live`. Returns False if the
    check is NOT in generated-checks.json (i.e. it's hand-written TOML — the caller guides
    that manual edit, since the zero-dep tool has no TOML writer)."""
    from . import proposals

    checks = proposals.load_generated_checks(cfg)
    hit = False
    for c in checks:
        if c.get("id") == check_id:
            c["expect"] = live
            hit = True
    if hit:
        proposals.save_generated_checks(cfg, checks)
    return hit


def last_verified_date(cfg: Config) -> str | None:
    """Newest verified_at across persisted provenance records (for the staleness nudge)."""
    dates = [r.get("verified_at") for r in load_provenance(cfg).values() if r.get("verified_at")]
    return max(dates) if dates else None


def stamp_last_verified(cfg: Config) -> None:
    """Epoch stamp read by the session-start freshness nudge. Legacy name/format."""
    out = cfg.path(cfg.index_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / LAST_VERIFIED_FILE).write_text(str(int(time.time())), encoding="utf-8")


def stamp_docs(cfg: Config, run_result: RunResult, today: date) -> list[str]:
    """Refresh `last_verified` in each doc whose non-SKIP checks all passed.

    The check's `doc` field must be a real repo-relative .md path for stamping;
    prose pointers ("see FOO.md section 3") are reported as unstampable.
    """
    by_doc: dict[str, list[CheckResult]] = {}
    for r in run_result.results:
        by_doc.setdefault(r.doc, []).append(r)
    actions = []
    for doc, results in sorted(by_doc.items()):
        statuses = {r.status for r in results if r.status != "SKIP"}
        if not statuses or statuses - {"PASS", "OK"}:
            continue
        path = cfg.path(doc)
        if not (doc.endswith(".md") and path.is_file()):
            actions.append(f"cannot stamp {doc!r} (not a repo-relative .md path)")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            new = frontmatter.set_field(text, "last_verified", today.isoformat())
        except ValueError:
            actions.append(f"cannot stamp {doc!r} (no frontmatter block)")
            continue
        if new != text:
            path.write_text(new, encoding="utf-8")
            actions.append(f"stamped {doc}: last_verified = {today.isoformat()}")
    return actions
