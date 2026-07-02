"""`librarian doctor` — sanity-check the installation, config, and wiring."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

from . import registry, verify
from .config import Config


@dataclass
class Finding:
    level: str   # ok | warn | problem
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
    rep = DoctorReport()
    rep.ok(f"python {sys.version.split()[0]} · root {cfg.root}")
    rep.ok(".librarian.toml parsed cleanly (unknown keys would have errored)")

    # Registry
    if cfg.path(cfg.artifacts_file).is_file():
        arts, errors = registry.load(cfg)
        if errors:
            for e in errors:
                rep.problem(e)
        rep.ok(f"artifact registry: {len(arts)} valid entr{'y' if len(arts) == 1 else 'ies'}")
    else:
        rep.warn(f"no {cfg.artifacts_file} — non-markdown artifacts are uncatalogued")

    # Git hook wiring
    if (cfg.root / ".git").exists():
        try:
            hooks_path = subprocess.run(
                ["git", "config", "core.hooksPath"], cwd=cfg.root,
                capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            hooks_path = ""
        pre_commit = cfg.root / ".githooks" / "pre-commit"
        if pre_commit.exists():
            if hooks_path == ".githooks":
                rep.ok("git core.hooksPath = .githooks (pre-commit active)")
            else:
                rep.warn("pre-commit hook exists but core.hooksPath is not set — run: "
                         "git config core.hooksPath .githooks")
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
    for name, src in sorted(cfg.sources.items()):
        used = sum(1 for c in cfg.checks if c.source == name)
        unset = [v for v in src.skip_if_unset if not os.environ.get(v)]
        if unset:
            rep.warn(f"source {name!r} ({used} checks): env not set ({', '.join(unset)}) — "
                     "its checks will SKIP")
            continue
        if src.skip_unless:
            probe_cmd = src.skip_unless
            try:
                probe = subprocess.run(["/bin/sh", "-c", probe_cmd], cwd=cfg.root,
                                       capture_output=True, text=True, timeout=30)
                if probe.returncode == 0:
                    rep.ok(f"source {name!r} ({used} checks): probe passed")
                else:
                    rep.warn(f"source {name!r} ({used} checks): probe failed "
                             f"(exit {probe.returncode}) — its checks will SKIP")
            except (OSError, subprocess.TimeoutExpired) as e:
                rep.warn(f"source {name!r}: probe errored ({e}) — its checks will SKIP")
        else:
            rep.ok(f"source {name!r} ({used} checks): no probe configured")
    if os.name == "nt" and cfg.checks:
        rep.warn("verify runs commands via /bin/sh — on native Windows use WSL/Git Bash")

    # Orphan baselines
    baselines = verify.load_baselines(cfg)
    orphan_baselines = sorted(set(baselines) - {c.id for c in cfg.checks})
    if orphan_baselines:
        rep.warn(f"baselines with no matching check (pruned by --update-baselines): "
                 f"{', '.join(orphan_baselines)}")

    # PATH check for hooks
    if shutil.which("librarian") is None:
        rep.warn("`librarian` is not on PATH — shell hooks will silently no-op "
                 "(pipx ensurepath, or install with pip)")
    return rep
