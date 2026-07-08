"""`librarian init` / `init --upgrade` / `init --uninstall`.

Idempotency contract: running init twice produces zero diff. Plain files are
skip-if-exists; AGENTS.md/CLAUDE.md get a marker-delimited managed block that is
replaced in place; `.claude/settings.json` is merged, never clobbered. Every
asset written is recorded (with a content hash) in `_index/.scaffold.json` so
`--upgrade` can tell "still ours, safe to refresh" from "user-modified, hands off."
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

MARKER_BEGIN = "<!-- librarian:begin (managed by `librarian init`; edits inside will be overwritten) -->"
MARKER_END = "<!-- librarian:end -->"
MANIFEST = ".scaffold.json"

HOOK_COMMAND = "bash .claude/hooks/librarian-session.sh"
PROMPT_HOOK_COMMAND = "bash .claude/hooks/librarian-prompt.sh"


@dataclass
class InitReport:
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)  # user-modified, left alone
    removed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _asset(name: str) -> str:
    return (resources.files("librarian") / "assets" / name).read_text(encoding="utf-8")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_manifest(root: Path, index_dir: str) -> dict:
    path = root / index_dir / MANIFEST
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"files": {}, "blocks": []}


def _save_manifest(root: Path, index_dir: str, manifest: dict) -> None:
    from . import __version__

    manifest["librarian_version"] = __version__
    out = root / index_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_managed(
    root: Path,
    rel: str,
    content: str,
    manifest: dict,
    report: InitReport,
    *,
    upgrade: bool,
    executable: bool = False,
) -> None:
    path = root / rel
    recorded = manifest["files"].get(rel)
    if path.exists():
        current = path.read_text(encoding="utf-8", errors="replace")
        if current == content:
            report.skipped.append(rel)
        elif upgrade and recorded and _sha(current) == recorded:
            path.write_text(content, encoding="utf-8")
            report.updated.append(rel)
        elif upgrade:
            report.kept.append(rel)
            return  # user-modified: leave the manifest hash as-is too
        else:
            report.skipped.append(rel)
            return  # init never overwrites an existing, differing file
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        report.written.append(rel)
    if executable:
        try:
            path.chmod(path.stat().st_mode | 0o111)
        except OSError:
            pass
    manifest["files"][rel] = _sha(content)


def upsert_block(text: str, block_content: str) -> str:
    """Insert or replace the marker-delimited managed block in a file's text."""
    block = f"{MARKER_BEGIN}\n{block_content.rstrip()}\n{MARKER_END}\n"
    begin = text.find(MARKER_BEGIN)
    if begin != -1:
        end = text.find(MARKER_END, begin)
        if end != -1:
            end += len(MARKER_END)
            if end < len(text) and text[end] == "\n":
                end += 1
            return text[:begin] + block + text[end:]
        # begin without end: treat everything from begin as the old block
        return text[:begin] + block
    if text and not text.endswith("\n"):
        text += "\n"
    sep = "\n" if text else ""
    return text + sep + block


def strip_block(text: str) -> str:
    begin = text.find(MARKER_BEGIN)
    if begin == -1:
        return text
    end = text.find(MARKER_END, begin)
    if end == -1:
        return text[:begin].rstrip() + "\n"
    end += len(MARKER_END)
    while end < len(text) and text[end] == "\n":
        end += 1
    head = text[:begin].rstrip()
    tail = text[end:]
    if head:
        return head + "\n" + ("\n" + tail if tail.strip() else "")
    return tail


def _apply_block(root: Path, rel: str, content: str, manifest: dict, report: InitReport) -> None:
    path = root / rel
    old = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    new = upsert_block(old, content)
    if new != old:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
        report.updated.append(f"{rel} (managed block)") if old else report.written.append(rel)
    else:
        report.skipped.append(f"{rel} (managed block)")
    if rel not in manifest["blocks"]:
        manifest["blocks"].append(rel)


def _merge_hook(hooks: dict, event: str, command: str) -> bool:
    """Append a command hook to `event` if absent. Returns True if it was added."""
    entries = hooks.setdefault(event, [])
    for entry in entries:
        for h in entry.get("hooks", []):
            if h.get("command") == command:
                return False
    entries.append({"hooks": [{"type": "command", "command": command}]})
    return True


def _merge_claude_settings(root: Path, report: InitReport) -> None:
    path = root / ".claude" / "settings.json"
    settings: dict = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            report.notes.append(
                ".claude/settings.json is not valid JSON — hooks NOT merged; add a SessionStart "
                f"hook (`{HOOK_COMMAND}`) and a UserPromptSubmit hook (`{PROMPT_HOOK_COMMAND}`) manually"
            )
            return
    hooks = settings.setdefault("hooks", {})
    merged = []
    if _merge_hook(hooks, "SessionStart", HOOK_COMMAND):
        merged.append("SessionStart")
    if _merge_hook(hooks, "UserPromptSubmit", PROMPT_HOOK_COMMAND):
        merged.append("UserPromptSubmit")
    if not merged:
        report.skipped.append(".claude/settings.json (hooks already present)")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    report.updated.append(f".claude/settings.json ({' + '.join(merged)} hook(s) merged)")


def init(root: Path, *, agent: str = "both", index_dir: str = "_index", upgrade: bool = False) -> InitReport:
    report = InitReport()
    manifest = _load_manifest(root, index_dir)

    _write_managed(
        root, ".librarian.toml", _asset("librarian.toml.template"), manifest, report, upgrade=False
    )  # config is user policy: never auto-upgrade
    from .registry import REGISTRY_TEMPLATE

    _write_managed(root, "librarian-artifacts.toml", REGISTRY_TEMPLATE, manifest, report, upgrade=False)
    _write_managed(
        root, "KNOWLEDGE_PROTOCOL.md", _asset("KNOWLEDGE_PROTOCOL.md"), manifest, report, upgrade=upgrade
    )
    _write_managed(
        root, "docs/NAVIGATOR.md", _asset("NAVIGATOR.template.md"), manifest, report, upgrade=False
    )  # becomes user content immediately
    _write_managed(root, "_inbox/README.md", _asset("inbox_README.md"), manifest, report, upgrade=upgrade)
    _write_managed(root, "_archive/README.md", _asset("archive_README.md"), manifest, report, upgrade=upgrade)
    gitkeep = root / "_inbox" / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("", encoding="utf-8")
    _write_managed(
        root,
        ".githooks/pre-commit",
        _asset("githooks/pre-commit"),
        manifest,
        report,
        upgrade=upgrade,
        executable=True,
    )

    if agent in ("agents-md", "both"):
        _apply_block(root, "AGENTS.md", _asset("AGENTS_BLOCK.md"), manifest, report)
    if agent in ("claude", "both"):
        _apply_block(root, "CLAUDE.md", _asset("CLAUDE_BLOCK.md"), manifest, report)
        _write_managed(
            root,
            ".claude/commands/librarian.md",
            _asset("claude/commands/librarian.md"),
            manifest,
            report,
            upgrade=upgrade,
        )
        _write_managed(
            root,
            ".claude/commands/librarian-dream.md",
            _asset("claude/commands/librarian-dream.md"),
            manifest,
            report,
            upgrade=upgrade,
        )
        _write_managed(
            root,
            ".claude/hooks/librarian-session.sh",
            _asset("claude/librarian-session.sh"),
            manifest,
            report,
            upgrade=upgrade,
            executable=True,
        )
        _write_managed(
            root,
            ".claude/hooks/librarian-prompt.sh",
            _asset("claude/librarian-prompt.sh"),
            manifest,
            report,
            upgrade=upgrade,
            executable=True,
        )
        _merge_claude_settings(root, report)

    _save_manifest(root, index_dir, manifest)
    report.notes.append("activate the git hook once per clone: git config core.hooksPath .githooks")
    return report


def uninstall(root: Path, *, index_dir: str = "_index") -> InitReport:
    """Remove unmodified scaffolded assets; strip managed blocks. Keeps config,
    the artifact registry, NAVIGATOR, and everything in _index/ (prints what it kept)."""
    report = InitReport()
    manifest = _load_manifest(root, index_dir)
    keep = {".librarian.toml", "librarian-artifacts.toml", "docs/NAVIGATOR.md"}
    for rel, sha in sorted(manifest["files"].items()):
        if rel in keep:
            report.kept.append(rel)
            continue
        path = root / rel
        if not path.exists():
            continue
        current = path.read_text(encoding="utf-8", errors="replace")
        if _sha(current) == sha:
            path.unlink()
            report.removed.append(rel)
        else:
            report.kept.append(f"{rel} (modified since scaffold)")
    for rel in manifest["blocks"]:
        path = root / rel
        if not path.exists():
            continue
        old = path.read_text(encoding="utf-8", errors="replace")
        new = strip_block(old)
        if not new.strip():
            path.unlink()
            report.removed.append(rel)
        elif new != old:
            path.write_text(new, encoding="utf-8")
            report.updated.append(f"{rel} (managed block removed)")
    mpath = root / index_dir / MANIFEST
    if mpath.exists():
        mpath.unlink()
        report.removed.append(f"{index_dir}/{MANIFEST}")
    report.notes.append(f"kept: .librarian.toml, librarian-artifacts.toml, docs/NAVIGATOR.md, {index_dir}/")
    return report
