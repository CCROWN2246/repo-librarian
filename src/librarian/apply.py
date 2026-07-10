"""`librarian apply` — execute proposal objects against the working tree.

Every apply is: (1) a per-target staleness gate — if ANY listed file changed since
the proposal was drafted, refuse and tell the user to re-dream; (2) an idempotent,
typed working-tree mutation (run-twice == zero diff); (3) an append to
_index/apply-log.jsonl. Reindexing and the mark-done decision live in the CLI layer.

apply NEVER commits to main implicitly, never force-writes, never deletes: archive
and merge are `git mv`-style moves + a status flip, reversible by construction. The
generative/irreversible risk caps (proposals.cap_tier) bound what may auto-commit,
never what a human may apply by hand.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from . import frontmatter, proposals
from .config import Config

APPLY_LOG = "apply-log.jsonl"

# Conflict-marker tokens (an on-disk data format). New product vocab is written; the
# legacy KB- tokens are still recognized (dual-parse) so proposals against docs written
# before the rename still apply.
DISPUTED_MARKERS = ("<!-- librarian:disputed", "<!-- KB-CONTRADICTED")
ACK_TOKENS = ("librarian:ack", "KB-ACK")
ACK_NEW = "librarian:ack"

# Terminal per-proposal results.
APPLIED, NOOP, STALE, REFUSED, ERROR = "applied", "noop", "stale", "refused", "error"


@dataclass
class Outcome:
    id: str
    type: str
    result: str
    detail: str
    targets: list[str]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "result": self.result,
            "detail": self.detail,
            "targets": self.targets,
        }


# --- marker helpers ------------------------------------------------------------


def _marker_index(lines: list[str], target_line: int | None) -> int | None:
    """Index of the conflict marker line nearest `target_line` (1-indexed), or the first
    one if `target_line` is None. Deterministic; line-drift tolerant; dual-parse."""
    idxs = [i for i, ln in enumerate(lines) if any(m in ln for m in DISPUTED_MARKERS)]
    if not idxs:
        return None
    if target_line is None:
        return idxs[0]
    return min(idxs, key=lambda i: (abs(i - (target_line - 1)), i))


def _drop_marker(text: str, target_line: int | None) -> str:
    lines = text.split("\n")
    idx = _marker_index(lines, target_line)
    if idx is None:
        return text
    del lines[idx]
    return "\n".join(lines)


# --- per-type handlers: (cfg, proposal, dry_run) -> (result, detail) -----------


def _read(cfg: Config, rel: str) -> str:
    return cfg.path(rel).read_text(encoding="utf-8")


def _apply_fix(cfg: Config, p: proposals.Proposal, dry: bool) -> tuple[str, str]:
    tgt = p.targets[0]
    path = cfg.path(tgt.path)
    text = _read(cfg, tgt.path)
    repl = p.action.get("replace") or {}
    old, new = repl.get("old", ""), repl.get("new", "")
    drop = bool(p.action.get("drop_marker"))
    if old and old in text:  # {old present} -> apply the replace (row 1)
        newtext = text.replace(old, new, 1)
        if drop:
            newtext = _drop_marker(newtext, tgt.line)
        result, detail = APPLIED, "replaced wrong text"
    elif new and new in text:  # {old absent, new present} -> idempotent (row 2)
        newtext = _drop_marker(text, tgt.line) if drop else text
        result = APPLIED if newtext != text else NOOP
        detail = "already corrected; dropped stale marker" if result == APPLIED else "already corrected"
    else:  # {old absent, new absent} -> someone else edited it (row 3)
        return STALE, f"neither old nor new text present in {tgt.path}; re-dream"
    if newtext != text and not dry:
        path.write_text(newtext, encoding="utf-8")
    return result, detail


def _apply_ack(cfg: Config, p: proposals.Proposal, dry: bool) -> tuple[str, str]:
    tgt = p.targets[0]
    path = cfg.path(tgt.path)
    text = _read(cfg, tgt.path)
    lines = text.split("\n")
    idx = _marker_index(lines, tgt.line)
    if idx is None:
        return STALE, "no conflict marker found near the line; re-dream"
    if any(a in lines[idx] for a in ACK_TOKENS):
        return NOOP, "marker already acknowledged"
    disputed = next(m for m in DISPUTED_MARKERS if m in lines[idx])
    lines[idx] = lines[idx].replace(disputed, f"{disputed} {ACK_NEW}", 1)
    if not dry:
        path.write_text("\n".join(lines), encoding="utf-8")
    return APPLIED, f"acknowledged ({ACK_NEW} added)"


def _apply_set_read_when(cfg: Config, p: proposals.Proposal, dry: bool) -> tuple[str, str]:
    tgt = p.targets[0]
    path = cfg.path(tgt.path)
    text = _read(cfg, tgt.path)
    rw = list(p.action.get("read_when", []))
    parsed = frontmatter.parse(text)
    if parsed is None:
        return STALE, "no frontmatter block; re-dream"
    if parsed.meta.get("read_when") == rw:
        return NOOP, "read_when already set"
    newtext = frontmatter.set_field(text, "read_when", rw)
    if not dry:
        path.write_text(newtext, encoding="utf-8")
    return APPLIED, f"set read_when ({len(rw)} phrase(s))"


def _apply_resolve_absence(cfg: Config, p: proposals.Proposal, dry: bool) -> tuple[str, str]:
    # Informational: records the audit verdict. A stale_claim's actual edit rides a
    # paired `fix` proposal; a confirmed_gap may spawn an `enrich_create`.
    verdict = p.action.get("verdict", "confirmed_gap")
    if verdict == "stale_claim":
        return APPLIED, "verdict recorded: stale_claim (edit via the paired fix proposal)"
    return APPLIED, f"verdict recorded: {verdict} (informational)"


def _flip_status(text: str, status: str) -> str:
    try:
        return frontmatter.set_field(text, "status", status)
    except ValueError:
        return text  # no frontmatter block; move the file anyway


def _archive_move(cfg: Config, src_rel: str, dest_rel: str, status: str, dry: bool) -> tuple[str, str]:
    src, dest = cfg.path(src_rel), cfg.path(dest_rel)
    if not src.exists():
        if dest.exists():
            return NOOP, "already archived"
        return STALE, "source missing and dest absent; re-dream"
    if dest.exists():
        return REFUSED, f"archive dest {dest_rel} already exists (won't clobber)"
    newtext = _flip_status(_read(cfg, src_rel), status)
    if dry:
        return APPLIED, f"would archive {src_rel} -> {dest_rel} (status={status})"
    src.write_text(newtext, encoding="utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return APPLIED, f"archived {src_rel} -> {dest_rel} (status={status})"


def archive_doc(
    cfg: Config, path_rel: str, *, to: str | None = None, status: str = "archived", dry: bool = False
) -> tuple[str, str, str]:
    """Retire one doc (status flip + move). Shared by the archive proposal handler and
    the direct `librarian archive` command. Returns (result, detail, dest_rel)."""
    dest_rel = to or f"{cfg.archive_dir}/{Path(path_rel).name}"
    result, detail = _archive_move(cfg, path_rel, dest_rel, status, dry)
    return result, detail, dest_rel


def _apply_archive(cfg: Config, p: proposals.Proposal, dry: bool) -> tuple[str, str]:
    tgt = p.targets[0]
    to = p.action.get("to")
    if not to:
        return ERROR, "archive proposal missing action.to"
    return _archive_move(cfg, tgt.path, to, p.action.get("set_status", "archived"), dry)


def _fold_carry_over(cfg: Config, p: proposals.Proposal, dry: bool) -> tuple[str, str] | None:
    """Fold a merge's `carry_over` text into the canonical, idempotently. apply OWNS this
    edit now (no hand-editing first — that was the false-STALE bug). The canonical is guarded
    HERE via action.canonical_sha256, not by the generic stale gate (which `apply_one`
    excludes it from for merges), so the fold can mutate it without self-STALE-ing on re-run.

    Returns an (result, detail) tuple only on refusal; None when the fold is done/absent."""
    a = p.action
    canonical = a.get("canonical")
    raw = a.get("carry_over") or []
    items = [raw] if isinstance(raw, str) else list(raw)
    carry = "\n\n".join(s for s in (str(x).strip() for x in items) if s)
    if not carry:
        return None  # nothing to fold
    cpath = cfg.path(canonical)
    if not cpath.exists():
        return STALE, f"canonical {canonical} missing; re-dream"
    ctext = _read(cfg, canonical)
    if carry in ctext:
        return None  # already folded -> idempotent, leave canonical untouched
    # not yet folded: guard against an EXTERNAL change to canonical since draft time
    canonical_sha = a.get("canonical_sha256")
    if canonical_sha is not None and proposals.file_sha256(cpath) != canonical_sha:
        return STALE, f"canonical {canonical} changed since draft — re-dream"
    if not dry:
        cpath.write_text(ctext.rstrip("\n") + "\n\n" + carry + "\n", encoding="utf-8")
    return None


def _apply_merge(cfg: Config, p: proposals.Proposal, dry: bool) -> tuple[str, str]:
    # apply's deterministic steps: (1) fold carry_over into the canonical (idempotent),
    # (2) retire the redundant doc.
    a = p.action
    redundant, canonical = a.get("redundant"), a.get("canonical")
    if not redundant or not canonical:
        return ERROR, "merge proposal missing action.canonical/redundant"
    refusal = _fold_carry_over(cfg, p, dry)
    if refusal is not None:
        return refusal
    if not a.get("then_archive", True):
        src = cfg.path(redundant)
        if not src.exists():
            return NOOP, "redundant doc already removed"
        newtext = _flip_status(_read(cfg, redundant), "archived")
        if newtext == _read(cfg, redundant):
            return NOOP, "redundant already marked archived"
        if not dry:
            src.write_text(newtext, encoding="utf-8")
        return APPLIED, f"marked {redundant} archived (merged into {canonical})"
    dest_rel = f"{cfg.archive_dir}/{Path(redundant).name}"
    result, detail = _archive_move(cfg, redundant, dest_rel, "archived", dry)
    if result == APPLIED:
        detail = f"merged {redundant} into {canonical}; {detail}"
    return result, detail


def _apply_enrich_create(cfg: Config, p: proposals.Proposal, dry: bool) -> tuple[str, str]:
    a = p.action
    new_path = a.get("new_path")
    if not new_path:
        return ERROR, "enrich_create missing action.new_path"
    dest = cfg.path(new_path)
    if dest.exists():
        return REFUSED, f"{new_path} already exists (won't clobber a provisional draft)"
    fm = dict(a.get("frontmatter") or {})
    fm.setdefault("status", a.get("status", "provisional"))
    content = frontmatter.serialize(fm) + a.get("body", "")
    if not dry:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    return APPLIED, f"created provisional doc {new_path}"


def _apply_add_check(cfg: Config, p: proposals.Proposal, dry: bool) -> tuple[str, str]:
    a = p.action
    check = dict(a.get("check") or {})
    cid = a.get("check_id") or check.get("id")
    if not cid:
        return ERROR, "add_check missing check_id"
    check.setdefault("id", cid)
    existing = proposals.load_generated_checks(cfg)
    for c in existing:
        if c.get("id") == cid and c == check:
            return NOOP, f"check {cid} already registered"
    if not dry:
        merged = [c for c in existing if c.get("id") != cid] + [check]
        proposals.save_generated_checks(cfg, merged)
    return APPLIED, f"registered check {cid} in generated-checks.json"


_HANDLERS = {
    "fix": _apply_fix,
    "ack": _apply_ack,
    "set_read_when": _apply_set_read_when,
    "resolve_absence": _apply_resolve_absence,
    "archive": _apply_archive,
    "merge": _apply_merge,
    "enrich_create": _apply_enrich_create,
    "add_check": _apply_add_check,
}


# --- orchestration -------------------------------------------------------------


def stale_targets(cfg: Config, p: proposals.Proposal) -> list[str]:
    """Paths whose current content hash no longer matches the draft-time guard."""
    return [t.path for t in p.targets if proposals.file_sha256(cfg.path(t.path)) != t.base_sha256]


def apply_one(cfg: Config, p: proposals.Proposal, *, dry_run: bool = False) -> Outcome:
    paths = [t.path for t in p.targets]
    stale = stale_targets(cfg, p)
    if p.type == "merge":
        # The canonical is intentionally mutated by the carry_over fold; its staleness is
        # guarded inside _apply_merge via action.canonical_sha256 (idempotency-aware), so it
        # must NOT trip the generic pre-handler stale gate (which would false-STALE on re-run).
        canonical = p.action.get("canonical")
        stale = [s for s in stale if s != canonical]
    if stale:
        detail = f"target(s) changed since draft: {', '.join(stale)} — re-dream"
        return Outcome(p.id, p.type, STALE, detail, paths)
    handler = _HANDLERS.get(p.type)
    if handler is None:
        return Outcome(p.id, p.type, ERROR, f"no apply handler for type {p.type!r}", paths)
    try:
        result, detail = handler(cfg, p, dry_run)
    except (OSError, ValueError, KeyError) as e:
        result, detail = ERROR, str(e)
    return Outcome(p.id, p.type, result, detail, paths)


def select(
    all_proposals: list[proposals.Proposal], *, only: set[str] | None, all_approved: bool
) -> list[proposals.Proposal]:
    """--only <id>… selects those ids (regardless of approval/applied — explicit re-apply
    is allowed); --all selects every approved proposal that is NOT already applied (so a
    second `apply --all` is a no-op, not a re-run of done work). --only is the terminal path
    the agent calls."""
    if only:
        return [p for p in all_proposals if p.id in only]
    if all_approved:
        return [p for p in all_proposals if p.approved and not p.applied]
    return []


def log_outcomes(cfg: Config, outcomes: list[Outcome], now: int | None = None) -> None:
    """Append one JSONL record per outcome to _index/apply-log.jsonl (audit trail)."""
    if not outcomes:
        return
    out = cfg.path(cfg.index_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = int(now if now is not None else time.time())
    lines = [json.dumps({"ts": ts, **o.to_dict()}, sort_keys=True) for o in outcomes]
    with (out / APPLY_LOG).open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
