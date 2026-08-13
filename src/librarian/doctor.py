"""`librarian doctor` — sanity-check the installation, config, and wiring."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

from . import catalog, checks, config, proposals, registry, verify
from .config import Config


@dataclass
class Finding:
    level: str  # ok | warn | problem
    message: str


@dataclass
class DoctorReport:
    findings: list[Finding] = field(default_factory=list)

    def ok(self, msg: str) -> None:
        self.findings.append(Finding("ok", msg))

    def warn(self, msg: str) -> None:
        self.findings.append(Finding("warn", msg))

    def problem(self, msg: str) -> None:
        self.findings.append(Finding("problem", msg))

    @property
    def has_problems(self) -> bool:
        return any(f.level == "problem" for f in self.findings)


def run(cfg: Config) -> DoctorReport:
    from . import scaffold

    rep = DoctorReport()
    rep.ok(f"python {sys.version.split()[0]} · root {cfg.root}")
    rep.ok(".librarian.toml parsed cleanly (unknown keys would have errored)")

    # SYS: nudge when the scaffolded protocol/glue predates the installed tool.
    stale = scaffold.scaffold_staleness(cfg)
    if stale:
        rep.warn(stale)

    # Registry (hand-authored TOML + the machine-authored overlay)
    arts, errors = registry.load(cfg)
    generated = registry.load_generated(cfg)
    for e in errors:
        rep.problem(e)
    if cfg.path(cfg.artifacts_file).is_file() or generated:
        machine = sum(1 for a in arts if a.get("_generated_fields"))
        detail = f" ({machine} carrying machine-authored fields)" if machine else ""
        rep.ok(f"artifact registry: {len(arts)} valid entr{'y' if len(arts) == 1 else 'ies'}{detail}")
    else:
        rep.warn(f"no {cfg.artifacts_file} — non-markdown artifacts are uncatalogued")

    # `_index/` mixes DERIVED output (CATALOG.md, STALENESS.md, catalog.json — regenerable
    # by `index`) with IRREPLACEABLE state (baselines, provenance, proposals, apply-log, and
    # the machine-authored checks/artifacts). Committed, that's recoverable. Gitignored, a
    # `rm -rf _index` destroys machine-authored work with no error and no way back — so the
    # dangerous configuration is the one to name.
    irreplaceable = [
        f
        for f in (
            verify.BASELINES_FILE,
            verify.PROVENANCE_FILE,
            proposals.PROPOSALS_FILE,
            proposals.GENERATED_CHECKS_FILE,
            registry.GENERATED_FILE,
        )
        if (cfg.path(cfg.index_dir) / f).is_file()
    ]
    if irreplaceable and (cfg.root / ".git").exists():
        try:
            ignored = (
                subprocess.run(
                    ["git", "check-ignore", "-q", str(cfg.path(cfg.index_dir) / irreplaceable[0])],
                    cwd=cfg.root,
                    capture_output=True,
                    timeout=10,
                ).returncode
                == 0
            )
        except (OSError, subprocess.TimeoutExpired):
            ignored = False
        if ignored:
            rep.problem(
                f"{cfg.index_dir}/ is gitignored but holds irreplaceable state "
                f"({', '.join(irreplaceable)}) — regenerating the index would destroy "
                "machine-authored work with no way back. Commit these, or move them out."
            )
        else:
            rep.ok(f"{cfg.index_dir}/ state is tracked ({len(irreplaceable)} irreplaceable file(s))")

    # V4: data files no verify check guards. The doc-side coverage scan has always nudged
    # about an unchecked claim; this is its data-side twin, and it is also the only thing
    # that surfaces `connect` — without it you have to already know the command exists.
    # Lives in doctor, not the status hook: it walks the filesystem, and the hook is
    # deliberately catalog-only so it stays cheap enough to run on every prompt.
    guarded = " ".join((c.cmd or "") + " " + (c.arg or "") for c in cfg.checks)
    try:
        draftable, _skipped = checks.scan(cfg, ".")
    except OSError:
        draftable = []
    unguarded = [rel for rel in draftable if rel not in guarded]
    if unguarded:
        shown = ", ".join(unguarded[:3]) + (f", +{len(unguarded) - 3} more" if len(unguarded) > 3 else "")
        rep.warn(
            f"{len(unguarded)} data file(s) no verify check guards ({shown}) — "
            "`librarian connect <dir>` drafts a row-count and schema guard for each"
        )
    elif draftable:
        rep.ok(f"data coverage: all {len(draftable)} scannable data file(s) are guarded by a check")

    # Machine-emitted checks the loader dropped. Silence here is the dangerous case: the
    # agent is told the check was registered, and it never runs.
    for cid in cfg.shadowed_checks:
        rep.problem(
            f"generated check {cid!r} is SHADOWED by a hand-written check of the same id in "
            f"{config.CONFIG_NAME} — the generated one never runs. Rename one of them."
        )
    for cid in cfg.invalid_generated_checks:
        rep.problem(
            f"generated check {cid!r} in {proposals.GENERATED_CHECKS_FILE} is malformed and was "
            "skipped (needs id, kind, exactly one of cmd/arg, and expect for assert)"
        )

    # Git hook wiring
    if (cfg.root / ".git").exists():
        try:
            hooks_path = subprocess.run(
                ["git", "config", "core.hooksPath"], cwd=cfg.root, capture_output=True, text=True, timeout=10
            ).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            hooks_path = ""
        pre_commit = cfg.root / ".githooks" / "pre-commit"
        if pre_commit.exists():
            if hooks_path == ".githooks":
                rep.ok("git core.hooksPath = .githooks (pre-commit active)")
            else:
                rep.warn(
                    "pre-commit hook exists but core.hooksPath is not set — run: "
                    "git config core.hooksPath .githooks"
                )
            if os.name != "nt" and not os.access(pre_commit, os.X_OK):
                rep.problem(".githooks/pre-commit is not executable — run: chmod +x .githooks/pre-commit")
    else:
        rep.warn("not a git repository — pre-commit catalog refresh unavailable")

    # Claude glue
    hook_sh = cfg.root / ".claude" / "hooks" / "librarian-session.sh"
    if cfg.agent_claude and not hook_sh.exists():
        rep.warn(".claude/hooks/librarian-session.sh missing — run `librarian init` to scaffold")

    # Verify sources + checks
    if not cfg.checks:
        rep.warn("no [[verify.checks]] defined — the `verified` tier has nothing backing it yet")
    if cfg.coverage_guard:
        try:
            c_arts, c_errs = registry.load(cfg)
            res = catalog.build(cfg, config.today(), c_arts, c_errs)
            gaps = len(res.coverage_gaps)
        except Exception:  # doctor must never crash on a coverage estimate
            gaps = 0
        if gaps:
            rep.warn(
                f"{gaps} doc(s) assert a checkable fact with no verify check — correctness coverage gap "
                "(see STALENESS.md; /librarian-dream can draft the checks)"
            )
        else:
            rep.ok(
                "correctness coverage: every doc asserting a checkable fact has a verify check (or none do)"
            )
    for name, src in sorted(cfg.sources.items()):
        used = sum(1 for c in cfg.checks if c.source == name)
        unset = [v for v in src.skip_if_unset if not os.environ.get(v)]
        if unset:
            rep.warn(
                f"source {name!r} ({used} checks): env not set ({', '.join(unset)}) — its checks will SKIP"
            )
            continue
        if src.skip_unless:
            probe_cmd = src.skip_unless
            try:
                probe = subprocess.run(
                    ["/bin/sh", "-c", probe_cmd], cwd=cfg.root, capture_output=True, text=True, timeout=30
                )
                if probe.returncode == 0:
                    rep.ok(f"source {name!r} ({used} checks): probe passed")
                else:
                    rep.warn(
                        f"source {name!r} ({used} checks): probe failed "
                        f"(exit {probe.returncode}) — its checks will SKIP"
                    )
            except (OSError, subprocess.TimeoutExpired) as e:
                rep.warn(f"source {name!r}: probe errored ({e}) — its checks will SKIP")
        else:
            rep.ok(f"source {name!r} ({used} checks): no probe configured")
    if os.name == "nt" and cfg.checks:
        rep.warn("verify runs commands via /bin/sh — on native Windows use WSL/Git Bash")

    # Orphan baselines — and surface a corrupt baselines file as a diagnostic (drift
    # detection is disabled while it is corrupt) rather than crashing or exiting silently.
    try:
        baselines = verify.load_baselines(cfg)
    except config.ConfigError as e:
        rep.warn(str(e))
        baselines = {}
    orphan_baselines = sorted(set(baselines) - {c.id for c in cfg.checks})
    if orphan_baselines:
        rep.warn(
            f"baselines with no matching check (pruned by --update-baselines): {', '.join(orphan_baselines)}"
        )

    # PATH check for hooks
    if shutil.which("librarian") is None:
        rep.warn(
            "`librarian` is not on PATH — shell hooks will silently no-op "
            "(pipx ensurepath, or install with pip)"
        )
    return rep
