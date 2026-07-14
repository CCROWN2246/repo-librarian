"""The `librarian` CLI.

Exit-code contract (uniform): 0 = success/clean · 1 = findings (drift, gate hit,
needs attention) · 2 = usage/config error. `--json` emits exactly one JSON
document on stdout; human chatter goes to stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import (
    __version__,
    backfill,
    catalog,
    config,
    doctor,
    dream,
    enrich,
    frontmatter,
    ingest,
    proposals,
    registry,
    render,
    scaffold,
    search,
    suggest,
    verify,
)
from . import (
    apply as apply_engine,
)
from .config import Config, ConfigError
from .output import Reporter, tag
from .proposals import ProposalError

STALE_VERIFY_DAYS = 7
NUDGE_FILE = ".last_nudge"  # epoch stamp throttling the UserPromptSubmit work-resumption nudge


def _read_epoch(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _write_epoch(path: Path, value: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(int(value)), encoding="utf-8")


def _add_common(p: argparse.ArgumentParser, *, json_flag: bool = True) -> None:
    p.add_argument(
        "--root", type=Path, default=None, help="repo root (default: walk up from cwd to .librarian.toml)"
    )
    p.add_argument("--quiet", action="store_true", help="suppress normal output")
    if json_flag:
        p.add_argument("--json", action="store_true", help="machine-readable output on stdout")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="librarian", description="A card catalog and a fact-checker for your repo's knowledge."
    )
    p.add_argument("--version", action="version", version=f"librarian {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="scaffold the librarian into this repo")
    _add_common(sp, json_flag=False)
    sp.add_argument(
        "--agent",
        choices=["claude", "agents-md", "both", "none"],
        default="both",
        help="which agent glue to scaffold (default: both)",
    )
    g = sp.add_mutually_exclusive_group()
    g.add_argument(
        "--upgrade", action="store_true", help="refresh unmodified scaffolded assets to this version"
    )
    g.add_argument(
        "--uninstall", action="store_true", help="remove unmodified scaffolded assets + managed blocks"
    )
    sp.add_argument(
        "--no-commit",
        action="store_true",
        help="don't auto-commit the scaffolding (default: commit it when the working tree was clean)",
    )

    sp = sub.add_parser("index", help="rebuild _index/ (CATALOG.md, STALENESS.md, catalog.json)")
    _add_common(sp)
    sp.add_argument(
        "--check", action="store_true", help="exit 1 if any [index].fail_on category is non-empty (CI gate)"
    )

    sp = sub.add_parser("suggest", help="auto-draft registry entries for uncovered code/data files")
    _add_common(sp, json_flag=False)
    sp.add_argument("--write", action="store_true", help="append drafts to the registry (default: print)")
    sp.add_argument("--domain", default="uncategorized", help="domain to stamp on drafts")

    sp = sub.add_parser("verify", help="fact-check doc claims against their live sources")
    _add_common(sp)
    sp.add_argument("--source", help="only checks of this source")
    sp.add_argument("--id", dest="id_glob", help="only check ids matching this glob")
    sp.add_argument("--kind", choices=["assert", "track"], help="only checks of this kind")
    sp.add_argument(
        "--update-baselines", action="store_true", help="record NEW/CHANGED track values as the new baselines"
    )
    sp.add_argument(
        "--stamp", action="store_true", help="refresh last_verified in docs whose checks all pass"
    )
    sp.add_argument(
        "--accept",
        metavar="CHECK_ID",
        help="update an assert check's expect to the current live value (deliberate sign-off)",
    )
    sp.add_argument("--dry-run", action="store_true", help="don't write any state files")

    sp = sub.add_parser("status", help="one-screen health summary")
    _add_common(sp)
    sp.add_argument(
        "--hook",
        action="store_true",
        help="hook mode: silent when clean, one-line nudge otherwise, always exit 0",
    )
    sp.add_argument(
        "--throttle",
        action="store_true",
        help="UserPromptSubmit mode: fast-path early-exit within the work-block "
        "([hooks].nudge_throttle_minutes) BEFORE loading catalog.json",
    )

    sp = sub.add_parser("search", help="rank catalog entries for a task phrase")
    _add_common(sp)
    sp.add_argument("terms", nargs="+", help="task phrase, e.g.: write athena query")
    sp.add_argument("-n", type=int, default=5, help="max results (default 5)")

    sp = sub.add_parser("backfill", help="bulk-stamp skeleton frontmatter onto .md docs lacking it")
    _add_common(sp, json_flag=False)
    sp.add_argument("dir", nargs="?", default=None, help="directory to backfill (default: docs root)")
    sp.add_argument("--write", action="store_true", help="apply (default: dry-run preview)")
    sp.add_argument("--domain", default="uncategorized")
    sp.add_argument("--status", default="draft")
    sp.add_argument("--authority", default=None)
    sp.add_argument("--recheck", default="90d")

    sp = sub.add_parser("ingest", help="triage _inbox/ uploads into the repo")
    _add_common(sp, json_flag=False)
    sp.add_argument("file", nargs="?", default=None, help="inbox filename (omit to list pending)")
    sp.add_argument("--domain", default=None)
    sp.add_argument("--status", default="reference")
    sp.add_argument(
        "--authority", default=None, help="trust tier from provenance (transcripts/third-party: unverified)"
    )
    sp.add_argument("--dest", default="docs", help="destination DIRECTORY (filename is appended)")
    sp.add_argument(
        "--read-when",
        dest="read_when",
        action="append",
        default=None,
        metavar="PHRASE",
        help="a routing phrase for when to read this doc (repeatable: --read-when X --read-when Y)",
    )
    sp.add_argument("--recheck", default="90d")
    sp.add_argument("--yes", action="store_true", help="accept defaults, no prompts")
    sp.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would be filed (path/tier/frontmatter); write nothing",
    )

    sp = sub.add_parser(
        "dream", help="build the deterministic maintenance worklist (drives /librarian-dream)"
    )
    _add_common(sp)
    sp.add_argument(
        "--mark-done",
        action="store_true",
        help="stamp the current worklist as reviewed (resets the 'dream is due' nudge)",
    )

    sp = sub.add_parser(
        "query", help="retrieve catalog pointers (id/path/freshness) by filter — pure stdlib, no bodies"
    )
    _add_common(sp)
    sp.add_argument("terms", nargs="*", help="optional phrase; every term must appear in an entry")
    sp.add_argument("--domain", help="filter to this domain (exact, case-insensitive)")
    sp.add_argument("--status", help="filter to this status (exact)")
    sp.add_argument("--tag", help="filter to entries carrying this tag")
    sp.add_argument("--id", dest="id_exact", help="filter to this exact id")
    sp.add_argument("--path", dest="path_sub", help="filter to entries whose path contains this substring")
    sp.add_argument("-n", type=int, default=50, help="max results (default 50)")

    sp = sub.add_parser("why", help="show the provenance for a verified fact (command, source, value, when)")
    _add_common(sp)
    sp.add_argument("terms", nargs="*", help="match against check id / doc / source / value (omit = all)")

    sp = sub.add_parser(
        "archive", help="retire a doc: flip status to archived, move to the archive dir, reindex"
    )
    _add_common(sp)
    sp.add_argument("path", help="repo-relative path of the doc to archive")
    sp.add_argument("--to", default=None, help="destination path (default: <archive_dir>/<basename>)")
    sp.add_argument("--dry-run", action="store_true", help="report what would happen; write nothing")

    sp = sub.add_parser(
        "enrich",
        help="list enrichable gaps (uncovered files + confirmed absences) — drives /librarian-enrich",
    )
    _add_common(sp)

    sp = sub.add_parser(
        "propose", help="append well-formed proposal object(s) to proposals.json (the dream producer)"
    )
    _add_common(sp)
    sp.add_argument(
        "file", nargs="?", default="-", help="JSON: one partial proposal or a list (default: stdin '-')"
    )
    sp.add_argument("--approved", action="store_true", help="mark the proposal(s) approved on creation")

    sp = sub.add_parser("apply", help="execute approved proposal objects against the working tree")
    _add_common(sp)
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true", dest="all_", help="apply every approved proposal")
    g.add_argument("--only", nargs="+", metavar="ID", help="apply these proposal ids (ignores approval)")
    g.add_argument(
        "--auto",
        action="store_true",
        help="apply proposals whose configured [automation] tier is branch/commit "
        "(default all-off = no-op); the trust-ladder pre-authorizes them, no per-item approval",
    )
    sp.add_argument(
        "--tier",
        choices=["off", "branch", "commit"],
        default="off",
        help="for --all/--only: max tier (commit auto-commits; capped by each proposal's risk). "
        "Ignored by --auto, which reads the per-type tier from [automation].",
    )
    sp.add_argument("--dry-run", action="store_true", help="report what would change; write nothing")

    sp = sub.add_parser("todos", help="list pending (unapplied) proposals as a numbered worklist")
    _add_common(sp)

    sp = sub.add_parser("doctor", help="sanity-check config, registry, hooks, and verify sources")
    _add_common(sp)
    return p


def _resolve_config(args) -> Config:
    root = args.root.resolve() if getattr(args, "root", None) else config.find_root()
    if root is None:
        raise ConfigError("no .librarian.toml found here or above (run `librarian init` first)")
    return config.load(root)


def _build_catalog(cfg: Config):
    artifacts, errors = registry.load(cfg)
    return catalog.build(cfg, config.today(), artifacts, errors)


def _git(root: Path, *args: str):
    import subprocess

    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    except OSError:
        return None


def _git_worktree_clean(root: Path) -> bool | None:
    """True/False if in a git repo (clean = no tracked-or-untracked changes), None if not a repo."""
    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if inside is None or inside.returncode != 0:
        return None
    status = _git(root, "status", "--porcelain")
    return status is not None and status.returncode == 0 and status.stdout.strip() == ""


def cmd_init(args, rep: Reporter) -> int:
    root = (args.root or Path.cwd()).resolve()
    # Capture cleanliness BEFORE scaffolding: only auto-commit when the tree was clean,
    # so init can never sweep the user's own uncommitted WIP into its scaffolding commit.
    was_clean = None if args.uninstall else _git_worktree_clean(root)
    if args.uninstall:
        r = scaffold.uninstall(root)
    else:
        r = scaffold.init(root, agent=args.agent, upgrade=args.upgrade)
    for label, items in (
        ("written", r.written),
        ("updated", r.updated),
        ("removed", r.removed),
        ("kept (yours)", r.kept),
        ("unchanged", r.skipped),
    ):
        for it in items:
            rep.say(f"  {label:12} {it}")
    for note in r.notes:
        rep.say(f"  note:        {note}")
    if not args.uninstall:
        try:
            cfg = config.load(root)
            res = _build_catalog(cfg)
            render.write_all(cfg, res)
            rep.say(f"  indexed:     {len(res.items)} entries -> {cfg.index_dir}/")
        except ConfigError as e:
            rep.warn(f"initial index failed: {e}")
        _maybe_commit_scaffolding(root, was_clean, no_commit=args.no_commit, rep=rep)
    return 0


def _maybe_commit_scaffolding(root: Path, was_clean: bool | None, *, no_commit: bool, rep: Reporter) -> None:
    """Commit the freshly-scaffolded files so the working tree is clean out of the box —
    but only when it was clean beforehand, so a user's own WIP is never swept in."""
    if was_clean is None:  # not a git repo
        return
    if no_commit or not was_clean:
        if not was_clean:
            rep.say("  note:        uncommitted changes present — commit the librarian scaffolding yourself.")
        return
    _git(root, "add", "-A")
    committed = _git(root, "commit", "-m", "chore: scaffold repo-librarian (librarian init)")
    if committed is not None and committed.returncode == 0:
        rep.say("  committed:   the scaffolding (working tree was clean).")
    else:
        rep.say("  note:        could not auto-commit the scaffolding; commit it yourself.")


def _index_summary_line(res) -> str:
    s = res.summary()
    ack = f" (+{s['acknowledged_conflicts']} ack)" if s["acknowledged_conflicts"] else ""
    inbox = f" · {s['inbox_pending']} awaiting intake (_inbox)" if s["inbox_pending"] else ""
    return (
        f"librarian index: {s['catalogued']} catalogued ({s['missing_frontmatter']} md-need-fm, "
        f"{s['unregistered']} unregistered, {s['flagged']} flagged, {s['orphans']} orphaned, "
        f"{s['open_conflicts']} open conflicts{ack}){inbox}"
    )


def cmd_index(args, rep: Reporter) -> int:
    cfg = _resolve_config(args)
    res = _build_catalog(cfg)
    render.write_all(cfg, res)
    if args.json:
        rep.emit_json(json.loads(render.catalog_json(res)))
    else:
        rep.say(_index_summary_line(res))
        for e in res.registry_errors:
            rep.warn(e)
    if args.check:
        failures = res.gate_failures(cfg.fail_on)
        if failures:
            rep.error(f"index --check gate hit: {', '.join(failures)} (see {cfg.index_dir}/STALENESS.md)")
            return 1
    return 0


def cmd_suggest(args, rep: Reporter) -> int:
    cfg = _resolve_config(args)
    res = _build_catalog(cfg)
    suggestions = suggest.build_suggestions(cfg, res)
    if not suggestions:
        rep.say("No uncovered code/data files — the registry covers everything the scan watches.")
        return 0
    blocks = [suggest.to_toml(s, config.today(), domain=args.domain) for s in suggestions]
    if args.write:
        reg = suggest.append_to_registry(cfg, blocks)
        res = _build_catalog(cfg)
        render.write_all(cfg, res)
        rep.say(
            f"appended {len(blocks)} draft entr{'y' if len(blocks) == 1 else 'ies'} to {reg.name} "
            "and reindexed."
        )
        rep.say("Review each draft: set the real domain/status and write read_when task phrases.")
    else:
        rep.say(
            f"# {len(blocks)} draft(s) — review, then paste into {cfg.artifacts_file} "
            "(or re-run with --write):\n"
        )
        for b in blocks:
            rep.say(b)
    return 0


def _verify_accept(cfg: Config, check_id: str, rep: Reporter) -> int:
    """`verify --accept <id>` (item 10): the guided, on-brand way to change what an assert
    check counts as correct — vs a raw .librarian.toml edit."""
    check = next((c for c in cfg.checks if c.id == check_id), None)
    if check is None:
        valid = ", ".join(sorted(c.id for c in cfg.checks)) or "(none)"
        rep.error(f"no check with id {check_id!r} (valid: {valid})")
        return 2
    if check.kind != "assert":
        rep.error(
            f"check {check_id!r} is kind={check.kind}; --accept is for assert checks "
            "(track checks use --update-baselines)"
        )
        return 2
    run = verify.run(cfg, only_id=check_id)
    r = next((x for x in run.results if x.id == check_id), None)
    if r is None or r.live is None:
        rep.error(f"could not read a live value for {check_id} (status {r.status if r else '?'})")
        return 2
    if verify.accept_expect(cfg, check_id, r.live):
        # 2.3b: the run we just did is DRIFT (that's WHY we're accepting). After accept the
        # check passes by construction (expect := live) — synthesize that PASS before
        # persisting, so provenance clears the failing signal now, not only at the next
        # verify (else the check stays FAILING in the greeting/STALENESS in the meantime).
        r.status, r.expect = "PASS", r.live
        verify.update_provenance(cfg, run, config.today())
        rep.say(f"  accepted: {check_id} expect -> {r.live!r} (generated-checks.json); check now PASSES.")
        rep.say("  You've intentionally changed what counts as correct. Commit to record it.")
        return 0
    # 2.3: a hand-written .librarian.toml check. The zero-dep tool never writes the user's
    # TOML (config.py invariant), so NOTHING was changed — say so honestly and exit 1 rather
    # than returning a false success. The DRIFT is real until the human edits the expect.
    rep.say(f"  NO CHANGE MADE — {check_id} lives in .librarian.toml, which the tool never edits.")
    rep.say("  Set its expect yourself and commit (you're changing what counts as correct):")
    rep.say(f'      expect = "{r.live}"')
    return 1


def cmd_verify(args, rep: Reporter) -> int:
    cfg = _resolve_config(args)
    if args.accept:
        return _verify_accept(cfg, args.accept, rep)
    run = verify.run(cfg, only_source=args.source, only_id=args.id_glob, only_kind=args.kind)
    actions: list[str] = []
    if not args.dry_run:
        verify.stamp_last_verified(cfg)
        verify.update_provenance(cfg, run, config.today())
        if args.update_baselines:
            actions += verify.update_baselines(cfg, run, config.today())
        if args.stamp or cfg.stamp_docs:
            actions += verify.stamp_docs(cfg, run, config.today())
    if args.json:
        rep.emit_json(
            {
                "results": [r.to_dict() for r in run.results],
                "summary": run.counts(),
                "actions": actions,
                "exit_code": 1 if run.failed else 0,
            }
        )
    else:
        for r in run.results:
            pairs = [("expect", r.expect), ("baseline", r.baseline), ("live", r.live)]
            extra = " ".join(f"{k}={v}" for k, v in pairs if v is not None)
            rep.say(f"{tag(r.status)} {r.source:10} {r.id:40} {extra}".rstrip())
            if r.status in ("DRIFT", "CHANGED", "ERROR"):
                rep.say(f"          -> update: {r.doc}")
            if r.error:
                rep.say(f"          -> {r.error}")
        for a in actions:
            rep.say(f"  {a}")
        c = run.counts()
        skips = f" · {c.get('SKIP', 0)} SKIP (source not connected)" if c.get("SKIP") else ""
        # 2.2: gloss DRIFT once so the verify vocabulary bridges to the "FAILING" status the
        # greeting/STALENESS use — same signal, two surfaces.
        rep.say(
            f"\n{len(run.results)} checks · {c.get('DRIFT', 0)} DRIFT (= failing check) · "
            f"{c.get('CHANGED', 0)} CHANGED (track) · {c.get('ERROR', 0)} ERROR{skips}"
        )
        # 2.1: verify does not rewrite STALENESS.md — nudge the operator to refresh it so the
        # persisted failing count and the catalog agree.
        if run.failed:
            rep.say("  a check is failing — run `librarian index` to refresh STALENESS.md.")
    return 1 if run.failed else 0


def _load_catalog_json(cfg: Config) -> dict | None:
    path = cfg.path(cfg.index_dir) / "catalog.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _verify_age_days(cfg: Config) -> int | None:
    path = cfg.path(cfg.index_dir) / verify.LAST_VERIFIED_FILE
    if not path.is_file():
        return None
    try:
        return int((time.time() - int(path.read_text().strip())) // 86400)
    except (ValueError, OSError):
        return None


def _catalog_token_estimate(cfg: Config) -> int:
    """Estimated always-load cost of CATALOG.md (~4 chars/token heuristic)."""
    path = cfg.path(cfg.index_dir) / "CATALOG.md"
    try:
        return path.stat().st_size // 4
    except OSError:
        return 0


def cmd_status(args, rep: Reporter) -> int:
    cfg = _resolve_config(args)
    if args.hook:
        # The work-block throttle. --throttle (UserPromptSubmit) early-exits BEFORE any
        # catalog load if we nudged within the window; SessionStart (--hook alone) always
        # runs but still stamps, so the prompts right after it stay quiet. One full check
        # per window, max — the hook never pays the catalog-load tax on every prompt.
        nudge_path = cfg.path(cfg.index_dir) / NUDGE_FILE
        window = cfg.nudge_throttle_minutes * 60
        if args.throttle:
            if window <= 0:
                return 0  # work-resumption nudge disabled ([hooks].nudge_throttle_minutes = 0)
            last = _read_epoch(nudge_path)
            if last is not None and (time.time() - last) < window:
                return 0
        _write_epoch(nudge_path, time.time())
    data = _load_catalog_json(cfg)
    if data is None:
        # status never rebuilds (it must stay cheap for the hook) — it reports on what exists.
        msg = f"no {cfg.index_dir}/catalog.json yet — run `librarian index`"
        if args.hook:
            print(f"Librarian: {msg}")
            return 0
        rep.say(msg)
        return 1
    s = data["summary"]
    age = _verify_age_days(cfg)
    attention = []
    if s["open_conflicts"]:
        attention.append(f"{s['open_conflicts']} OPEN conflict(s)")
    # Item 2: a registered check that STARTED failing (DRIFT/ERROR) must reach the greeting,
    # not just `librarian why`. Read from provenance.json (cli layer, one cheap file read —
    # never re-run verify in the hook). Lead with impact, right after conflicts.
    failing = verify.failing_checks(cfg)
    if failing:
        ago = f", as of {failing[0]['verified_at']}" if failing[0].get("verified_at") else ""
        attention.append(f"{len(failing)} FAILING check(s){ago} — run `librarian verify`")
    if s["orphans"]:
        attention.append(f"{s['orphans']} orphaned registry entr(ies)")
    if s["missing_frontmatter"]:
        attention.append(f"{s['missing_frontmatter']} md missing frontmatter")
    if s["registry_errors"]:
        attention.append(f"{s['registry_errors']} registry error(s)")
    if s["inbox_pending"]:
        attention.append(f"{s['inbox_pending']} awaiting intake")
    if s["frontmatter_warnings"]:
        attention.append(f"{s['frontmatter_warnings']} frontmatter warning(s)")
    verify_stale = bool(cfg.checks) and (age is None or age >= STALE_VERIFY_DAYS)
    if verify_stale:
        attention.append(
            "facts unverified " + (f"{age}d" if age is not None else "ever") + " — run `librarian verify`"
        )
    catalog_tokens = _catalog_token_estimate(cfg)
    if cfg.catalog_token_budget and catalog_tokens > cfg.catalog_token_budget:
        attention.append(
            f"CATALOG.md ≈ {catalog_tokens // 1000}k tokens (> {cfg.catalog_token_budget // 1000}k "
            "budget) — archive retired docs or split the corpus"
        )
    # dream-due nudge — computed from catalog.json (no filesystem walk, hook-cheap)
    dream_wl = dream.from_catalog_json(data, cfg.dream_merge_similarity)
    dream_due, _dream_reason = dream.is_due(cfg, dream_wl)
    if dream_due:
        attention.append(f"{dream_wl.total} maintenance item(s) ready — run /librarian-dream")

    if args.hook:
        if attention:
            print("Librarian: " + " · ".join(attention) + f" — see {cfg.index_dir}/STALENESS.md")
        return 0
    if args.json:
        rep.emit_json(
            {
                "summary": s,
                "verify_age_days": age,
                "attention": attention,
                "flagged": s["flagged"],
                "unregistered": s["unregistered"],
                "catalog_tokens_estimate": catalog_tokens,
            }
        )
        return 1 if attention else 0
    rep.say(
        f"librarian status — {s['catalogued']} catalogued "
        f"({s['docs']} docs + {s['artifacts']} artifacts, {s['domains']} domains)"
    )
    rep.say(
        f"  flagged: {s['flagged']} · unregistered code/data: {s['unregistered']} · "
        f"absence-claims: {s['absence_claims']} · catalog ≈ {catalog_tokens / 1000:.1f}k tokens"
    )
    rep.say(
        "  facts last verified: "
        + (f"{age}d ago" if age is not None else "never")
        + (f" · {len(cfg.checks)} checks configured" if cfg.checks else " · no checks configured")
    )
    if attention:
        rep.say("  needs attention: " + " · ".join(attention))
        return 1
    rep.say("  clean.")
    return 0


def cmd_search(args, rep: Reporter) -> int:
    cfg = _resolve_config(args)
    data = _load_catalog_json(cfg)
    if data is None:
        res = _build_catalog(cfg)
        render.write_all(cfg, res)
        data = json.loads(render.catalog_json(res))
    entries = data["entries"]
    scored = search.rank(entries, args.terms)
    if not scored and len(entries) <= search.BODY_SEARCH_MAX_DOCS:
        # two-tier fallback (A1b): re-read doc bodies only on a zero metadata hit
        scored = search.rank_bodies(cfg, entries, args.terms)
    top = scored[: args.n]
    if args.json:
        rep.emit_json(
            [
                {
                    "score": s,
                    "id": e.get("id"),
                    "title": e.get("title"),
                    "path": e["path"],
                    "domain": e.get("domain"),
                    "read_when": e.get("read_when", []),
                }
                for s, e in top
            ]
        )
        return 0 if top else 1
    if not top:
        if len(entries) > search.BODY_SEARCH_MAX_DOCS:
            rep.say(
                f"no metadata match, and the corpus is too large ({len(entries)} docs) "
                "to scan bodies — try grep"
            )
        else:
            rep.say("nothing in the catalog mentions that — try `librarian index` to refresh, or grep")
        return 1
    for _score, e in top:
        rw = ", ".join(str(x) for x in e.get("read_when", [])) or "-"
        rep.say(f"  {e.get('id', '?'):32} {e['path']:44} read_when: {rw}")
    return 0


def cmd_backfill(args, rep: Reporter) -> int:
    cfg = _resolve_config(args)
    targets = backfill.plan(cfg, args.dir)
    if not targets:
        rep.say("No .md files need frontmatter — all covered (or none found).")
        return 0
    mode = "APPLYING" if args.write else "DRY RUN"
    auth = f" authority={args.authority}" if args.authority else ""
    rep.say(
        f"{mode} — {len(targets)} file(s) need frontmatter (domain={args.domain} status={args.status}{auth}):"
    )
    for _, p, _text in targets:
        rep.say(f'  {"stamped" if args.write else "would stamp"}: {p.path}  (id={p.id}, title="{p.title}")')
    if args.write:
        backfill.apply(
            cfg,
            targets,
            domain=args.domain,
            status=args.status,
            authority=args.authority,
            recheck=args.recheck,
            today=config.today(),
        )
        res = _build_catalog(cfg)
        render.write_all(cfg, res)
        rep.say(
            f"\nDone. Reindexed. The {len(targets)} new docs show as status={args.status} in "
            f"{cfg.index_dir}/STALENESS.md — that's your triage worklist."
        )
    else:
        rep.say("\nRe-run with --write to apply. Then refine each doc's domain/read_when/status/authority.")
    return 0


def _prompt(question: str, default: str, *, yes: bool) -> str:
    if yes or not sys.stdin.isatty():
        return default
    answer = input(f"{question} [{default}]: ").strip()
    return answer or default


def _suggest_authority(name: str) -> str:
    """Advisory trust-tier suggestion from source cues (E4). NEVER auto-applied — it
    only informs the refusal message + --dry-run. Safe-by-default: unknown -> unverified."""
    low = name.lower()
    unverified_cues = ("transcript", "call", "slack", "standup", "meeting", "recap", "notes", "chat")
    if any(c in low for c in unverified_cues):
        return "unverified"
    curated_cues = ("guide", "spec", "readme", "policy", "runbook", "design", "doc")
    if any(c in low for c in curated_cues):
        return "curated"
    return "unverified"


def cmd_ingest(args, rep: Reporter) -> int:
    cfg = _resolve_config(args)
    if args.file is None:
        pend = ingest.pending(cfg)
        if not pend:
            rep.say(f"{cfg.inbox_dir}/ is empty — nothing awaiting intake.")
            return 0
        rep.say(f"{len(pend)} file(s) awaiting intake in {cfg.inbox_dir}/:")
        for f in pend:
            rep.say(f"  {f}")
        rep.say("\nIngest one with: librarian ingest <file> [--domain X --authority unverified --dest docs]")
        return 0

    # 1.2: reduce a path that already carries the inbox prefix (or any dir) to its
    # basename before anything else — ingest is inbox-triage only, so the file must
    # live in _inbox/, and the refusal message below must quote the SAME form the
    # accept path resolves. (Do NOT resolve the arg as-given: ingest unlinks the
    # source after the move, so an arbitrary path could delete a real repo file.)
    args.file = Path(args.file).name

    # Item 1 (CRITICAL): the trust tier is the one decision that must never be a silent
    # default. In a non-interactive context (agent-driven; no TTY) the walkthrough is
    # unreachable, so REFUSE rather than guess. Filing location gets safe defaults; the
    # trust tier does not.
    non_interactive = args.yes or not sys.stdin.isatty()
    if non_interactive and args.authority is None:
        suggested = _suggest_authority(args.file)
        rep.error(
            f"can't ask which trust tier to use for {args.file} — not running in an interactive "
            f"terminal, and no --authority was given, so I won't guess.\n"
            f"  Re-run with --authority (suggested: {suggested}).\n"
            "  Tiers: verified / curated / unverified — transcripts & third-party notes are unverified."
        )
        return 2

    domain = args.domain or _prompt("domain", "uncategorized", yes=args.yes)
    # Defense-in-depth: even the interactive/enter fallback defaults to unverified, matching
    # the tool's own policy (transcripts are unverified), never the trusting `curated`.
    authority = args.authority or _prompt(
        "authority (verified/curated/unverified — transcripts are unverified)", "unverified", yes=args.yes
    )
    dest = args.dest or _prompt("destination directory", "docs", yes=args.yes)
    try:
        result = ingest.ingest_file(
            cfg,
            args.file,
            domain=domain,
            status=args.status,
            authority=authority,
            dest=dest,
            recheck=args.recheck,
            today=config.today(),
            read_when=args.read_when,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, FileExistsError, ValueError) as e:
        rep.error(str(e))
        return 2

    # Disclose any silently-used defaults. Computed for BOTH the dry-run preview and the
    # real filing so the operator sees the full consequence either way (1.4).
    defaults_used = []
    if args.domain is None:
        defaults_used.append(f"domain={domain}")
    if args.authority is None:
        defaults_used.append(f"authority={authority}")
    below_verified = str(authority).lower() != "verified"

    if args.dry_run:
        rep.say(f"  DRY RUN — would file {cfg.inbox_dir}/{args.file} -> {result.moved_to}")
        rep.say(f"  domain={domain}  authority={authority}  status={args.status}")
        if result.preview:
            block = frontmatter.find_block(result.preview)
            head = result.preview[: block[1]] if block else result.preview[:400]
            rep.say("  frontmatter it would write:\n" + "\n".join("    " + ln for ln in head.splitlines()))
        if defaults_used:
            rep.say(f"  would note: default(s) used ({', '.join(defaults_used)}) — REVIEW before trusting.")
        if below_verified:
            rep.say(
                "  would require: conflict-check this against existing verified facts before trusting it."
            )
        rep.say("\n  Nothing written. Re-run without --dry-run to file it.")
        return 0

    rep.say(
        f"  filed: {cfg.inbox_dir}/{args.file} -> {result.moved_to}"
        + (" (frontmatter added)" if result.frontmatter_added else "")
    )
    if defaults_used:
        rep.say(
            f"  NOTE: default(s) used ({', '.join(defaults_used)}) — no flags given; REVIEW before trusting."
        )
    # A3 (D3-conflict): the tool itself runs the conflict-check and REPORTS candidates —
    # no CLI backstop is left to an agent's reflex, and nothing is auto-quarantined. Search
    # the PRE-ingest catalog (build in-memory if none exists yet) and exclude the just-filed
    # doc so it never self-matches. Markdown only — a data artifact asserts no prose claim.
    conflicts = []
    if args.file.endswith(".md"):
        cat = _load_catalog_json(cfg)
        if cat is None:
            cat = json.loads(render.catalog_json(_build_catalog(cfg)))
        entries = [e for e in cat.get("entries", []) if e.get("path") != result.moved_to]
        try:
            text = cfg.path(result.moved_to).read_text(encoding="utf-8")
        except OSError:
            text = ""
        # The claim is title + read_when + body — NOT the frontmatter field names/tier values
        # (those pollute the query and make every same-domain doc a weak false candidate).
        parsed = frontmatter.parse(text)
        if parsed:
            meta = parsed.meta
            head = str(meta.get("title", "")) + " " + " ".join(str(x) for x in (meta.get("read_when") or []))
            claim = head + "\n" + text[parsed.span[1] :]
        else:
            claim = text
        terms = search.claim_terms(claim)
        if terms and entries:
            scored = search.rank(entries, terms)
            if not scored and len(entries) <= search.BODY_SEARCH_MAX_DOCS:
                scored = search.rank_bodies(cfg, entries, terms)
            conflicts = [e for _s, e in scored[:3]]
    if conflicts:
        rep.say("  possible conflict(s) — you decide (nothing auto-quarantined):")
        for e in conflicts:
            rep.say(f"    - {e.get('id') or e['path']} ({e['path']})")
        if below_verified:
            rep.say(
                "    if this contradicts a verified fact, quarantine it with a librarian:disputed marker."
            )
    elif below_verified:
        # No overlap surfaced, but an unverified claim still needs a human conflict-check.
        rep.say(
            "  NEXT (required): conflict-check this against existing verified facts before trusting it — "
            "no overlapping doc surfaced, but confirm before you rely on it."
        )
    if result.artifact_block:
        rep.say(f"\n  non-markdown artifact — add this entry to {cfg.artifacts_file}:\n")
        rep.say(result.artifact_block)
    res = _build_catalog(cfg)
    render.write_all(cfg, res)
    rep.say(f"  reindexed: {len(res.items)} entries")
    return 0


_TYPE_LABEL = {
    "fix": "fix a wrong value",
    "ack": "acknowledge a disputed claim",
    "archive": "archive a doc",
    "merge": "merge duplicate docs",
    "set_read_when": "set routing phrases",
    "resolve_absence": "resolve an absence-claim",
    "enrich_create": "draft a provisional doc",
    "add_check": "add a verify check",
}


def cmd_todos(args, rep: Reporter) -> int:
    """E3: the deferred/pending proposals ARE the backlog once apply writes state back
    (item 4). Render them as a numbered, plain-language list; numbers map to ids so an agent
    can say `apply 1 3` and translate to `apply --only <id> <id>`."""
    cfg = _resolve_config(args)
    props = proposals.load(cfg)
    # Reconcile a crash-stale writeback: an id the apply-log records as applied counts as
    # applied even if its proposals.json flag is stale (Finding B — log wins).
    landed = apply_engine.applied_ids_from_log(cfg)

    def _is_applied(p) -> bool:
        return p.applied or p.id in landed

    pending = [p for p in props if not _is_applied(p)]
    applied = [p for p in props if _is_applied(p)]
    if args.json:
        rep.emit_json(
            {
                "pending": [
                    {"n": i, "id": p.id, "type": p.type, "approved": p.approved, "rationale": p.rationale}
                    for i, p in enumerate(pending, 1)
                ],
                "applied": [
                    {"id": p.id, "type": p.type, "applied_at": p.applied_at, "result": p.result}
                    for p in applied
                ],
            }
        )
        return 1 if pending else 0
    if not pending:
        msg = (
            f"No pending proposals. ({len(applied)} already applied.)"
            if applied
            else "No proposals yet — run /librarian-dream to draft some."
        )
        rep.say(msg)
        return 0
    rep.say(f"{len(pending)} pending proposal(s) — apply by number (e.g. 'apply 1 3') or 'all':")
    for i, p in enumerate(pending, 1):
        mark = " ✓approved" if p.approved else ""
        rep.say(f"  {i}. {_TYPE_LABEL.get(p.type, p.type)}{mark} — {p.rationale or p.id}")
    if applied:
        rep.say(f"\n  ({len(applied)} already applied)")
    return 1


def cmd_doctor(args, rep: Reporter) -> int:
    cfg = _resolve_config(args)
    report = doctor.run(cfg)
    if args.json:
        rep.emit_json([f.__dict__ for f in report.findings])
    else:
        icon = {"ok": "[OK]     ", "warn": "[WARN]   ", "problem": "[PROBLEM]"}
        for f in report.findings:
            rep.say(f"{icon[f.level]} {f.message}")
    return 1 if report.has_problems else 0


def cmd_dream(args, rep: Reporter) -> int:
    cfg = _resolve_config(args)
    res = _build_catalog(cfg)
    wl = dream.from_catalog_result(res, cfg.dream_merge_similarity)
    # Inject the verify failing-check signal (provenance-sourced, display-only — never
    # feeds the delta gate). The pure engine stays unaware of verify state (item 2).
    wl.failing_checks = verify.failing_checks(cfg)
    if args.mark_done:
        dream.mark_done(cfg, wl)
        rep.say(f"marked {wl.total} worklist item(s) reviewed — the dream nudge is reset.")
        return 0
    due, reason = dream.is_due(cfg, wl)
    if args.json:
        rep.emit_json({"due": due, "reason": reason, "worklist": wl.to_dict()})
        return 1 if due else 0
    c = wl.counts()
    rep.say(
        f"dream worklist: {c['open_conflicts']} conflict(s) · {c['merge_candidates']} merge "
        f"candidate(s) · {c['read_when_todos']} routing TODO(s) · {c['absence_claims']} absence-claim(s) "
        f"· {c['retirement_candidates']} retirement candidate(s) · {c['coverage_gaps']} coverage gap(s) "
        f"· {c['failing_checks']} failing check(s)"
    )
    rep.say(f"  {'DUE' if due else 'not due'}: {reason}")
    if wl.failing_checks:
        rep.say("  failing checks (verify DRIFT/ERROR — run `librarian verify` to refresh before fixing):")
        for x in wl.failing_checks:
            detail = f"expect={x['expect']} live={x['live']}" if x["status"] == "DRIFT" else x["status"]
            rep.say(f"    {x['id']}  ({detail}) -> {x['doc']}")
    if wl.open_conflicts:
        rep.say("  conflicts:")
        for x in wl.open_conflicts:
            rep.say(f"    {x['path']}:{x['line']}")
    if wl.merge_candidates:
        rep.say("  merge candidates:")
        for x in wl.merge_candidates:
            rep.say(f"    {x['a']}  <->  {x['b']}  (sim {x['similarity']}, {x['domain']})")
    if wl.read_when_todos:
        rep.say("  routing TODOs (empty/placeholder read_when):")
        for x in wl.read_when_todos:
            rep.say(f"    {x['path']}")
    if wl.absence_claims:
        rep.say("  absence-claims to audit:")
        for x in wl.absence_claims:
            rep.say(f"    {x['path']}:{x['line']}")
    if wl.retirement_candidates:
        rep.say("  retirement candidates (terminal status, still in the docs tree):")
        for x in wl.retirement_candidates:
            rep.say(f"    {x['path']}  ({x['evidence']})")
    if wl.coverage_gaps:
        rep.say("  coverage gaps (checkable fact, no verify check — advisory, doesn't trigger the nudge):")
        for x in wl.coverage_gaps:
            rep.say(f"    {x['path']}  (claim: {x.get('text', '')})")
    if due:
        rep.say(
            "\nRun /librarian-dream to draft proposals on a branch, "
            "or `librarian dream --mark-done` to dismiss."
        )
    return 1 if due else 0


def cmd_query(args, rep: Reporter) -> int:
    cfg = _resolve_config(args)
    data = _load_catalog_json(cfg)
    if data is None:
        res = _build_catalog(cfg)
        render.write_all(cfg, res)
        data = json.loads(render.catalog_json(res))
    stale_ids = {s.get("id") for s in data.get("flags", {}).get("stale", [])}
    terms = [t.lower() for t in args.terms]
    dom = args.domain.lower() if args.domain else None
    out = []
    for e in data.get("entries", []):
        if dom and str(e.get("domain", "")).lower() != dom:
            continue
        if args.status and str(e.get("status", "")) != args.status:
            continue
        if args.tag and args.tag not in [str(x) for x in e.get("tags", [])]:
            continue
        if args.id_exact and str(e.get("id", "")) != args.id_exact:
            continue
        if args.path_sub and args.path_sub not in str(e.get("path", "")):
            continue
        if terms:
            hay = " ".join(
                [
                    str(e.get("title", "")),
                    str(e.get("id", "")),
                    str(e.get("domain", "")),
                    " ".join(str(x) for x in e.get("tags", [])),
                    " ".join(str(x) for x in e.get("read_when", [])),
                ]
            ).lower()
            if not all(t in hay for t in terms):
                continue
        out.append(e)
    out.sort(key=lambda e: str(e.get("path", "")))
    out = out[: args.n]
    rows = [
        {
            "id": e.get("id"),
            "title": e.get("title"),
            "path": e.get("path"),
            "domain": e.get("domain"),
            "status": e.get("status"),
            "authority": e.get("authority"),
            "last_verified": e.get("last_verified"),
            "read_when": e.get("read_when", []),
            "tags": e.get("tags", []),
            "kind": e.get("kind"),
            "stale": e.get("id") in stale_ids,
        }
        for e in out
    ]
    if args.json:
        rep.emit_json({"count": len(rows), "results": rows})
        return 0 if rows else 1
    if not rows:
        rep.say("no catalog entries match — refine the filter, or `librarian index` to refresh")
        return 1
    for r in rows:
        flag = " [STALE]" if r["stale"] else ""
        rep.say(
            f"  {str(r['id']):28} {str(r['path']):44} "
            f"status={r['status']} verified={r['last_verified'] or '-'}{flag}"
        )
    return 0


def cmd_why(args, rep: Reporter) -> int:
    cfg = _resolve_config(args)
    records = verify.load_provenance(cfg)  # keyed by check_id
    if not records:
        rep.say(f"no provenance yet — run `librarian verify` (writes {cfg.index_dir}/provenance.json)")
        return 1
    terms = [t.lower() for t in args.terms]
    matched = []
    for cid in sorted(records):
        r = records[cid]
        hay = " ".join(
            str(r.get(k, "")) for k in ("check_id", "doc", "source", "live", "expect", "baseline")
        ).lower()
        if not terms or all(t in hay for t in terms):
            matched.append(r)
    if args.json:
        rep.emit_json({"count": len(matched), "records": matched})
        return 0 if matched else 1
    if not matched:
        rep.say("no matching verified fact — try a check id, doc path, or value; or `librarian verify`")
        return 1
    for r in matched:
        rep.say(f"{r.get('check_id')} [{r.get('status')}]  (verified {r.get('verified_at', '?')})")
        vals = [f"{k}={r[k]}" for k in ("live", "expect", "baseline") if r.get(k) is not None]
        if vals:
            rep.say("  fact:    " + " · ".join(vals))
        rep.say(f"  source:  {r.get('source', '?')}")
        if r.get("command"):
            rep.say(f"  command: {r['command']}")
        rep.say(f"  backs:   {r.get('doc', '?')}")
    return 0


def _repo_rel(cfg: Config, given: str) -> str:
    """Best-effort repo-relative path: prefer as-given (relative to root), else resolve
    against cwd for a human running from a subdirectory."""
    if cfg.path(given).exists():
        return given
    p = Path(given)
    absp = (p if p.is_absolute() else Path.cwd() / p).resolve()
    try:
        return absp.relative_to(cfg.root.resolve()).as_posix()
    except ValueError:
        return given


def cmd_archive(args, rep: Reporter) -> int:
    cfg = _resolve_config(args)
    rel = _repo_rel(cfg, args.path)
    result, detail, dest = apply_engine.archive_doc(cfg, rel, to=args.to, dry=args.dry_run)
    reindexed = False
    if result == apply_engine.APPLIED and not args.dry_run:
        res = _build_catalog(cfg)
        render.write_all(cfg, res)
        reindexed = True
    if args.json:
        rep.emit_json(
            {
                "result": result,
                "detail": detail,
                "path": rel,
                "dest": dest,
                "dry_run": args.dry_run,
                "reindexed": reindexed,
            }
        )
    else:
        rep.say(f"  [{result}] {rel} -> {dest}: {detail}")
        if reindexed:
            rep.say("  reindexed. (reversible: git mv it back + flip status to un-retire)")
    if result == apply_engine.ERROR:
        return 2
    if result in (apply_engine.STALE, apply_engine.REFUSED):
        return 1
    return 0


def cmd_enrich(args, rep: Reporter) -> int:
    cfg = _resolve_config(args)
    res = _build_catalog(cfg)
    gaps = enrich.detect_gaps(cfg, res, proposals.load(cfg))
    sources = sorted(cfg.sources)
    if args.json:
        rep.emit_json({"count": len(gaps), "gaps": [g.to_dict() for g in gaps], "sources": sources})
        return 1 if gaps else 0
    if not gaps:
        rep.say("no enrichable gaps — coverage is complete and no confirmed gaps are outstanding.")
        return 0
    rep.say(
        f"enrichment worklist: {len(gaps)} gap(s). "
        f"Sources available to query: {', '.join(sources) if sources else '(none configured)'}"
    )
    for g in gaps:
        rep.say(f"  [{g.kind}] {g.ref} — {g.detail}")
    rep.say(
        "\nRun /librarian-enrich to draft provisional, source-verified docs (propose-only). "
        "A gap with no non-empty source evidence is flagged, never drafted."
    )
    return 1


def cmd_propose(args, rep: Reporter) -> int:
    cfg = _resolve_config(args)
    if args.file == "-":
        raw = sys.stdin.read()
    else:
        try:
            raw = Path(args.file).read_text(encoding="utf-8")
        except OSError as e:
            rep.error(f"cannot read {args.file}: {e}")
            return 2
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        rep.error(f"invalid JSON: {e}")
        return 2
    partials = data if isinstance(data, list) else [data]
    existing = proposals.load(cfg)
    existing_by_id = {p.id: p for p in existing}
    existing_ids = set(existing_by_id)
    # Finding B (reactivation): re-proposing an id that already LANDED resets it to unapplied
    # (upsert replaces it with the fresh, applied=False object), silently re-surfacing done
    # work in todos/apply. Warn loudly. Applied state comes from the flag OR the apply-log.
    landed = existing_ids & apply_engine.applied_ids_from_log(cfg)
    built = [proposals.build_from_partial(cfg, pt, approved=args.approved) for pt in partials]
    replaced = [p.id for p in built if p.id in existing_ids]
    reactivated = [
        p.id for p in built if p.id in landed or (existing_by_id.get(p.id) and existing_by_id[p.id].applied)
    ]
    for pid in reactivated:
        rep.warn(
            f"{pid} was already applied — re-proposing resets its flag, but the apply-log still "
            f"gates it out of `apply --all`/`todos`; run `apply --only {pid}` to force a re-apply"
        )
    merged = proposals.upsert(existing, built)
    proposals.save(cfg, merged)
    if args.json:
        rep.emit_json(
            {
                "added": [p.id for p in built],
                "replaced": replaced,
                "reactivated": reactivated,
                "total": len(merged),
                "proposals": [p.to_dict() for p in built],
            }
        )
    else:
        for p in built:
            verb = "replaced" if p.id in existing_ids else "proposed"
            rep.say(f"  {verb} {p.type} {p.id}{' (approved)' if p.approved else ''} — {p.rationale}")
        rep.say(f"  {len(merged)} proposal(s) now in {cfg.index_dir}/{proposals.PROPOSALS_FILE}")
    return 0


def _commit_applied(cfg: Config, props, rep: Reporter) -> bool:
    """tier=commit: stage + commit the applied changes on the CURRENT branch (never
    main implicitly — the caller's branch is wherever they are). Best-effort."""
    import subprocess

    ids = " ".join(p.id for p in props)
    msg = f"chore(librarian): apply {len(props)} proposal(s)\n\n{ids}"
    try:
        subprocess.run(["git", "-C", str(cfg.root), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(cfg.root), "commit", "-m", msg], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, OSError) as e:
        rep.warn(f"tier=commit but git commit failed: {e}")
        return False


def _apply_noop(args, rep: Reporter, msg: str) -> int:
    """Emit an empty apply result (JSON-aware) for the nothing-to-do early returns."""
    if args.json:
        rep.emit_json(
            {
                "dry_run": args.dry_run,
                "auto": args.auto,
                "tier": args.tier,
                "applied": 0,
                "reindexed": False,
                "marked_done": False,
                "committed": False,
                "outcomes": [],
            }
        )
    else:
        rep.say(msg)
    return 0


def cmd_apply(args, rep: Reporter) -> int:
    cfg = _resolve_config(args)
    all_props = proposals.load(cfg)
    if not all_props:
        return _apply_noop(
            args,
            rep,
            f"no proposals in {cfg.index_dir}/{proposals.PROPOSALS_FILE} — run /librarian-dream first",
        )

    # In --auto mode the tier comes per-proposal from [automation] (config is the
    # pre-authorization); otherwise from --tier over the selected/approved set.
    def resolved_tier(p) -> str:
        source = cfg.tier_for(p.type) if args.auto else args.tier
        return proposals.effective_tier(p, source)

    only = set(args.only) if args.only else None
    if args.auto:
        selected = [p for p in all_props if resolved_tier(p) != "off"]
    else:
        # Reconcile a crash-stale writeback: an id the apply-log marks applied is treated as
        # applied on the --all path even if proposals.json still says False (Finding B).
        selected = apply_engine.select(
            all_props,
            only=only,
            all_approved=args.all_,
            applied_ids=apply_engine.applied_ids_from_log(cfg),
        )
        if only:
            for m in sorted(only - {p.id for p in selected}):
                rep.warn(f"no proposal with id {m}")
    if not selected:
        return _apply_noop(
            args,
            rep,
            "nothing auto-appliable — every proposal's [automation] tier is off (propose-only)"
            if args.auto
            else "nothing selected (no approved proposals, or --only matched none)",
        )

    # apply_batch runs `selected` in order (id-hash-sorted) and threads intra-batch creation
    # awareness so a paired enrich_create + add_check lands its check regardless of order (5.3).
    outcomes = apply_engine.apply_batch(cfg, selected, dry_run=args.dry_run)
    by_id = {p.id: p for p in selected}
    if not args.dry_run:
        apply_engine.log_outcomes(cfg, outcomes)
        # Writeback (item 4): proposals.json is the single source of truth for "what's
        # still pending". Mark proposals that landed (applied, or idempotent noop) so a
        # fresh session, `apply --all`, or `librarian todos` never re-surfaces done work.
        done = {o.id: o.result for o in outcomes if o.result in (apply_engine.APPLIED, apply_engine.NOOP)}
        if done:
            stamp = config.today().isoformat()  # injectable date, never wall-clock (determinism)
            changed = False
            for p in all_props:
                if p.id in done and not p.applied:
                    p.applied, p.applied_at, p.result = True, stamp, done[p.id]
                    changed = True
            if changed:
                proposals.save(cfg, all_props)

    applied_any = any(o.result == apply_engine.APPLIED for o in outcomes)
    marked_done = False
    if applied_any and not args.dry_run:
        res = _build_catalog(cfg)
        render.write_all(cfg, res)
        wl = dream.from_catalog_result(res, cfg.dream_merge_similarity)
        if wl.empty:  # never blanket-mark-done after a partial apply (eng-review C3)
            dream.mark_done(cfg, wl)
            marked_done = True

    committed = False
    committable = [
        by_id[o.id]
        for o in outcomes
        if o.result == apply_engine.APPLIED and resolved_tier(by_id[o.id]) == "commit"
    ]
    if committable and not args.dry_run:
        committed = _commit_applied(cfg, committable, rep)

    if args.json:
        rep.emit_json(
            {
                "dry_run": args.dry_run,
                "auto": args.auto,
                "tier": args.tier,
                "applied": sum(1 for o in outcomes if o.result == apply_engine.APPLIED),
                "reindexed": applied_any and not args.dry_run,
                "marked_done": marked_done,
                "committed": committed,
                "outcomes": [o.to_dict() for o in outcomes],
            }
        )
    else:
        for o in outcomes:
            rep.say(f"  [{o.result}] {o.type} {o.id} — {o.detail}")
        if marked_done:
            rep.say("  worklist now empty — dream nudge reset")
        if committed:
            rep.say(f"  committed {len(committable)} proposal(s) at tier=commit")
    needs_attention = any(
        o.result in (apply_engine.STALE, apply_engine.ERROR, apply_engine.REFUSED) for o in outcomes
    )
    return 1 if needs_attention else 0


COMMANDS = {
    "init": cmd_init,
    "index": cmd_index,
    "suggest": cmd_suggest,
    "verify": cmd_verify,
    "status": cmd_status,
    "search": cmd_search,
    "backfill": cmd_backfill,
    "ingest": cmd_ingest,
    "dream": cmd_dream,
    "query": cmd_query,
    "why": cmd_why,
    "archive": cmd_archive,
    "enrich": cmd_enrich,
    "propose": cmd_propose,
    "apply": cmd_apply,
    "todos": cmd_todos,
    "doctor": cmd_doctor,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rep = Reporter(as_json=getattr(args, "json", False), quiet=args.quiet)
    try:
        return COMMANDS[args.command](args, rep)
    except (ConfigError, ProposalError) as e:
        rep.error(str(e))
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
