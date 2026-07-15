"""The proposal object — the automation spine (see docs/roadmap/SPEC-proposal-object.md).

A proposal is a machine-applyable maintenance/generation unit. `librarian-dream`
(and later `librarian-enrich`) emit these instead of prose; `librarian apply`
consumes them; the trust-ladder decides which auto-apply; the PR bot renders them
as checkboxes. One schema, four consumers, two producers.

`schema_version` is **1** and this file is a COMPATIBILITY SURFACE: once consuming
repos carry `_index/proposals.json`, a bump is breaking. Change it as deliberately
as STALENESS.md line 3. NOTE (apply-state fields `applied`/`applied_at`/`result`):
these are additive and emitted only on applied proposals, so roll-FORWARD is safe;
roll-BACK is not — a librarian predating them will reject a proposals.json that
carries them (the strict unknown-key loader). Fine at ~1 consumer, but stated, not silent.

Pure engine: dataclasses + validation + id/hash helpers + load/save. All policy
enforcement that needs the working tree (staleness, the fix truth-table) lives in
apply.py; all I/O sequencing lives in the CLI layer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = "1"
PROPOSALS_FILE = "proposals.json"
GENERATED_CHECKS_FILE = "generated-checks.json"

# The 8 proposal types. fix/ack/archive/merge/set_read_when/resolve_absence are
# maintenance (librarian-dream); enrich_create/add_check are generation (enrich).
TYPES = (
    "fix",
    "ack",
    "archive",
    "merge",
    "set_read_when",
    "resolve_absence",
    "enrich_create",
    "add_check",
)

WRITES_TO = ("branch", "main")
# Tier ordering for the trust-ladder (off < branch < commit).
TIERS = ("off", "branch", "commit")
_TIER_RANK = {t: i for i, t in enumerate(TIERS)}


class ProposalError(Exception):
    """A malformed or self-inconsistent proposal; maps to exit code 2."""


@dataclass
class Target:
    path: str
    base_sha256: str
    line: int | None = None

    def to_dict(self) -> dict:
        d: dict = {"path": self.path, "base_sha256": self.base_sha256}
        if self.line is not None:
            d["line"] = self.line
        return d


@dataclass
class Provenance:
    source: str = ""
    command: str | None = None
    evidence: str | None = None
    drafted_at: str = ""
    drafted_by: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class Risk:
    reversible: bool = True
    generative: bool = False
    writes_to: str = "branch"

    def to_dict(self) -> dict:
        return {"reversible": self.reversible, "generative": self.generative, "writes_to": self.writes_to}


@dataclass
class Proposal:
    type: str
    targets: list[Target]
    action: dict
    provenance: Provenance = field(default_factory=Provenance)
    risk: Risk = field(default_factory=Risk)
    rationale: str = ""
    approved: bool = False
    # Apply-time state (written back by `librarian apply` so proposals.json is the single
    # source of truth for "what's still pending"). Emitted ONLY when applied, so unapplied
    # proposals serialize identically to before (minimal golden churn). None of these feed
    # compute_id, so writeback never changes an id.
    applied: bool = False
    applied_at: str | None = None  # a date from the injectable clock (config.today()), never wall-clock
    result: str | None = None
    id: str = ""  # filled/verified on validate

    def to_dict(self) -> dict:
        d: dict = {
            "schema_version": SCHEMA_VERSION,
            "id": self.id,
            "type": self.type,
            "approved": self.approved,
            "targets": [t.to_dict() for t in self.targets],
            "action": self.action,
            "rationale": self.rationale,
            "provenance": self.provenance.to_dict(),
            "risk": self.risk.to_dict(),
        }
        if self.applied:
            d["applied"] = True
            if self.applied_at is not None:
                d["applied_at"] = self.applied_at
            if self.result is not None:
                d["result"] = self.result
        return d


# --- id / hashing --------------------------------------------------------------


def file_sha256(path: Path) -> str:
    """Whole-file content hash (v1 staleness granularity). Missing file -> ''."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _action_signature(ptype: str, targets: list[Target], action: dict) -> str:
    """The identity slice of an action: what makes two proposals the SAME logical
    change so a re-draft after an unrelated edit dedupes to one id.

    Deliberately excludes the *corrected* content (fix.new, set_read_when phrases,
    the enriched body) — those legitimately differ between drafts of the same fix.
    """
    a = action or {}
    if ptype == "fix":
        # Defensive: a malformed action (replace not a dict) must not crash the id
        # computation — validation reports it cleanly afterward (fail loud, not a traceback).
        rep = a.get("replace")
        return "old=" + str(rep.get("old", "") if isinstance(rep, dict) else "")
    if ptype == "ack":
        lines = ",".join(str(t.line) for t in targets)
        return "mark=" + str(a.get("mark", "")) + "@" + lines
    if ptype == "archive":
        return "to=" + str(a.get("to", ""))
    if ptype == "merge":
        return "canonical=" + str(a.get("canonical", "")) + "|redundant=" + str(a.get("redundant", ""))
    if ptype == "set_read_when":
        return ""  # identity is the target path alone (fill routing for this doc)
    if ptype == "resolve_absence":
        return "@" + ",".join(str(t.line) for t in targets)  # the claim location
    if ptype == "enrich_create":
        return "new_path=" + str(a.get("new_path", ""))
    if ptype == "add_check":
        return "check_id=" + str(a.get("check_id", ""))
    return ""


def compute_id(ptype: str, targets: list[Target], action: dict) -> str:
    """id = 'p_' + sha256[:12] over type + sorted target paths + action signature.

    EXCLUDES base_sha256, rationale, provenance, approved -> re-drafting the same
    logical proposal after a file edit yields the same id and dedupes.
    """
    paths = sorted(t.path for t in targets)
    sig = _action_signature(ptype, targets, action)
    payload = "\x00".join([ptype, *paths, sig])
    return "p_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


# --- validation / (de)serialization -------------------------------------------


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ProposalError(msg)


def _target_from_dict(d: dict, where: str) -> Target:
    _require(isinstance(d, dict), f"{where}: target must be a table")
    unknown = set(d) - {"path", "base_sha256", "line"}
    _require(not unknown, f"{where}: unknown target key(s): {', '.join(sorted(unknown))}")
    _require(isinstance(d.get("path"), str) and d["path"], f"{where}: target.path is required")
    _require(isinstance(d.get("base_sha256"), str), f"{where}: target.base_sha256 is required")
    line = d.get("line")
    _require(line is None or isinstance(line, int), f"{where}: target.line must be an int")
    return Target(path=d["path"], base_sha256=d["base_sha256"], line=line)


def from_dict(d: dict, *, where: str = "proposal") -> Proposal:
    _require(isinstance(d, dict), f"{where}: expected a table")
    d = dict(d)
    sv = str(d.pop("schema_version", SCHEMA_VERSION))
    _require(
        sv == SCHEMA_VERSION,
        f"{where}: unsupported schema_version {sv!r} (this librarian supports {SCHEMA_VERSION})",
    )

    ptype = d.pop("type", None)
    _require(ptype in TYPES, f"{where}: type must be one of {', '.join(TYPES)}, got {ptype!r}")

    raw_targets = d.pop("targets", None)
    _require(isinstance(raw_targets, list) and raw_targets, f"{where}: targets must be a non-empty array")
    targets = [_target_from_dict(t, f"{where}.targets[{i}]") for i, t in enumerate(raw_targets)]

    action = d.pop("action", None)
    _require(isinstance(action, dict), f"{where}: action must be a table")

    prov_raw = d.pop("provenance", {}) or {}
    _require(isinstance(prov_raw, dict), f"{where}: provenance must be a table")
    prov_unknown = set(prov_raw) - {"source", "command", "evidence", "drafted_at", "drafted_by"}
    _require(not prov_unknown, f"{where}: unknown provenance key(s): {', '.join(sorted(prov_unknown))}")
    provenance = Provenance(**prov_raw)

    risk_raw = d.pop("risk", {}) or {}
    _require(isinstance(risk_raw, dict), f"{where}: risk must be a table")
    risk_unknown = set(risk_raw) - {"reversible", "generative", "writes_to"}
    _require(not risk_unknown, f"{where}: unknown risk key(s): {', '.join(sorted(risk_unknown))}")
    risk = Risk(
        reversible=bool(risk_raw.get("reversible", True)),
        generative=bool(risk_raw.get("generative", False)),
        writes_to=str(risk_raw.get("writes_to", "branch")),
    )
    _require(risk.writes_to in WRITES_TO, f"{where}: risk.writes_to must be one of {', '.join(WRITES_TO)}")

    rationale = d.pop("rationale", "")
    approved = bool(d.pop("approved", False))
    applied = bool(d.pop("applied", False))
    applied_at = d.pop("applied_at", None)
    result = d.pop("result", None)
    given_id = d.pop("id", None)

    _require(not d, f"{where}: unknown key(s): {', '.join(sorted(d))}")

    p = Proposal(
        type=ptype,
        targets=targets,
        action=action,
        provenance=provenance,
        risk=risk,
        rationale=rationale,
        approved=approved,
        applied=applied,
        applied_at=applied_at if isinstance(applied_at, str) else None,
        result=result if isinstance(result, str) else None,
    )
    canonical = compute_id(p.type, p.targets, p.action)
    if given_id is not None and given_id != canonical:
        raise ProposalError(
            f"{where}: id {given_id!r} does not match its content (expected {canonical!r}); "
            "the object was hand-edited or corrupted"
        )
    p.id = canonical
    _validate_type_specifics(p, where)
    return p


def _validate_type_specifics(p: Proposal, where: str) -> None:
    """Per-type invariants beyond the shared shape. The accuracy wall for generation:
    an enrich_create MUST carry non-empty source evidence (the empty-source guard, R1 —
    a source that returned nothing can never justify drafting "we have zero X")."""
    a = p.action
    if p.type == "fix":
        # A fix rewrites text via action.replace = {"old": <find>, "new": <value>}. Reject a
        # malformed shape at propose time so it fails LOUD (ProposalError) instead of crashing
        # id-computation/apply with an AttributeError or silently no-op'ing at apply.
        rep = a.get("replace")
        _require(
            isinstance(rep, dict),
            f"{where}: fix requires action.replace to be an object with 'old' and 'new'",
        )
        old, new = rep.get("old", ""), rep.get("new", "")
        _require(
            isinstance(old, str) and isinstance(new, str),
            f"{where}: fix action.replace.old and .new must be strings",
        )
        _require(
            old.strip() != "" or new.strip() != "",
            f"{where}: fix action.replace needs a non-empty 'old' (text to find) or "
            "'new' (the already-applied value)",
        )
    elif p.type == "enrich_create":
        _require(bool(a.get("new_path")), f"{where}: enrich_create requires action.new_path")
        evidence = p.provenance.evidence
        _require(
            isinstance(evidence, str) and evidence.strip() != "",
            f"{where}: enrich_create requires non-empty provenance.evidence — the live-source value "
            "that justifies the draft. Empty/zero source => flag the gap, never draft (R1).",
        )
    elif p.type == "add_check":
        chk = a.get("check")
        _require(
            isinstance(chk, dict) and bool(chk.get("id") or a.get("check_id")),
            f"{where}: add_check requires action.check with an id",
        )
    elif p.type == "merge":
        # carry_over may be absent, a bare str, a list[str] (LEGACY body text), or a
        # list of structured ops {target: read_when|tags|body, content: str|list[str]}.
        # Validate the structured shape so a malformed fold fails LOUD at propose time,
        # not silently at apply (or by corrupting the canonical doc).
        raw = a.get("carry_over")
        if raw is not None and not isinstance(raw, str):
            _require(isinstance(raw, list), f"{where}: merge carry_over must be a string or a list")
            for i, item in enumerate(raw):
                if isinstance(item, str):
                    continue  # legacy list[str]: appended to the body
                _require(
                    isinstance(item, dict),
                    f"{where}: carry_over[{i}] must be a string or an object",
                )
                _require(
                    item.get("target") in ("read_when", "tags", "body"),
                    f"{where}: carry_over[{i}].target must be read_when, tags, or body",
                )
                content = item.get("content")
                ok = (isinstance(content, str) and content.strip()) or (
                    isinstance(content, list) and bool(content) and all(isinstance(x, str) for x in content)
                )
                _require(
                    bool(ok),
                    f"{where}: carry_over[{i}].content must be non-empty text or a list of strings",
                )


def make(
    ptype: str,
    targets: list[Target],
    action: dict,
    *,
    provenance: Provenance | None = None,
    risk: Risk | None = None,
    rationale: str = "",
    approved: bool = False,
) -> Proposal:
    """Construct a proposal with its id computed. The producer-side builder."""
    p = Proposal(
        type=ptype,
        targets=list(targets),
        action=action,
        provenance=provenance or Provenance(),
        risk=risk if risk is not None else default_risk(ptype),
        rationale=rationale,
        approved=approved,
    )
    p.id = compute_id(p.type, p.targets, p.action)
    return p


def build_from_partial(cfg, partial: dict, *, approved: bool = False) -> Proposal:
    """Turn a producer's partial proposal into a validated one. The agent supplies the
    JUDGMENT (type, target paths + optional line, action, rationale, provenance); the CLI
    supplies DETERMINISM: hash each target file for its base_sha256, compute the id, fill
    the risk profile. This is what `librarian propose` calls so the dream agent never
    hand-computes a hash. Missing base_sha256 is filled from the current file on disk.
    """
    _require(isinstance(partial, dict), "proposal: expected an object")
    ptype = partial.get("type")
    _require(ptype in TYPES, f"proposal: type must be one of {', '.join(TYPES)}, got {ptype!r}")

    raw_targets = partial.get("targets")
    _require(isinstance(raw_targets, list) and raw_targets, "proposal: targets must be a non-empty array")
    targets = []
    for i, t in enumerate(raw_targets):
        _require(isinstance(t, dict), f"proposal.targets[{i}]: expected an object")
        path = t.get("path")
        _require(isinstance(path, str) and path, f"proposal.targets[{i}]: path is required")
        unknown = set(t) - {"path", "base_sha256", "line"}
        _require(not unknown, f"proposal.targets[{i}]: unknown key(s): {', '.join(sorted(unknown))}")
        base = t.get("base_sha256")
        if base is None:
            base = file_sha256(cfg.path(path))  # hash the file as it is right now
        line = t.get("line")
        _require(line is None or isinstance(line, int), f"proposal.targets[{i}]: line must be an int")
        targets.append(Target(path=path, base_sha256=base, line=line))

    action = partial.get("action")
    _require(isinstance(action, dict), "proposal: action must be an object")

    prov_raw = partial.get("provenance") or {}
    _require(isinstance(prov_raw, dict), "proposal: provenance must be an object")
    try:
        provenance = Provenance(**prov_raw)
    except TypeError as e:
        raise ProposalError(f"proposal.provenance: {e}") from e

    risk = None
    if "risk" in partial:
        risk_raw = partial["risk"]
        _require(isinstance(risk_raw, dict), "proposal: risk must be an object")
        try:
            risk = Risk(**risk_raw)
        except TypeError as e:
            raise ProposalError(f"proposal.risk: {e}") from e

    p = make(
        ptype,
        targets,
        action,
        provenance=provenance,
        risk=risk,
        rationale=partial.get("rationale", ""),
        approved=approved,
    )
    # Round-trip through strict validation (writes_to enum, etc.) before it lands.
    return from_dict(p.to_dict())


def upsert(existing: list[Proposal], incoming: list[Proposal]) -> list[Proposal]:
    """Merge proposals by id — an incoming re-draft replaces the prior one, others are
    kept. Order-stable by id (matches dump()'s sort), so run-twice = zero diff."""
    by_id = {p.id: p for p in existing}
    for p in incoming:
        by_id[p.id] = p
    return [by_id[k] for k in sorted(by_id)]


def default_risk(ptype: str) -> Risk:
    """The conservative default risk profile per type (the accuracy wall's floor).

    A producer may override, but never *loosen* past what cap_tier enforces.
    """
    if ptype == "enrich_create":
        return Risk(reversible=True, generative=True, writes_to="branch")
    if ptype in ("fix", "merge"):
        return Risk(reversible=False, generative=False, writes_to="branch")  # text edits: caught in review
    # ack / archive / set_read_when / add_check / resolve_absence (informational):
    # reversible, non-generative.
    return Risk(reversible=True, generative=False, writes_to="branch")


# --- trust-ladder cap (the accuracy wall) -------------------------------------


def cap_tier(p: Proposal) -> str:
    """The MAX tier a proposal may auto-apply at, overriding any config. Invariants:
    generative -> branch; irreversible -> branch; archive/merge -> branch;
    writes_to main -> off (needs a separate explicit opt-in, never reachable by tier).
    """
    if p.risk.writes_to == "main":
        return "off"
    if p.risk.generative or not p.risk.reversible:
        return "branch"
    if p.type in ("archive", "merge"):
        return "branch"
    return "commit"


def effective_tier(p: Proposal, configured: str) -> str:
    """min(configured, cap_tier(p)) in the off<branch<commit ordering."""
    if configured not in _TIER_RANK:
        raise ProposalError(f"unknown tier {configured!r} (valid: {', '.join(TIERS)})")
    cap = cap_tier(p)
    return configured if _TIER_RANK[configured] <= _TIER_RANK[cap] else cap


# --- persistence --------------------------------------------------------------


def _index_path(cfg, name: str) -> Path:
    return cfg.path(cfg.index_dir) / name


def load(cfg) -> list[Proposal]:
    """Read _index/proposals.json. Missing file -> []. Malformed -> ProposalError."""
    path = _index_path(cfg, PROPOSALS_FILE)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ProposalError(f"{path}: unreadable proposals.json: {e}") from e
    _require(isinstance(data, dict), f"{path}: expected a top-level object")
    sv = str(data.get("schema_version", SCHEMA_VERSION))
    _require(sv == SCHEMA_VERSION, f"{path}: unsupported schema_version {sv!r}")
    raw = data.get("proposals", [])
    _require(isinstance(raw, list), f"{path}: 'proposals' must be an array")
    return [from_dict(p, where=f"{path}#proposals[{i}]") for i, p in enumerate(raw)]


def dump(proposals: list[Proposal]) -> str:
    """Canonical serialization (sorted keys, stable order) for minimal git diffs."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "proposals": [p.to_dict() for p in sorted(proposals, key=lambda x: x.id)],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def save(cfg, proposals: list[Proposal]) -> None:
    out = cfg.path(cfg.index_dir)
    out.mkdir(parents=True, exist_ok=True)
    _index_path(cfg, PROPOSALS_FILE).write_text(dump(proposals), encoding="utf-8")


# --- generated-checks.json sidecar (add_check target) -------------------------


def load_generated_checks(cfg) -> list[dict]:
    """Machine-emitted verify checks (from add_check proposals). config.load merges
    these AFTER the hand-written TOML checks. Missing/malformed -> []."""
    path = _index_path(cfg, GENERATED_CHECKS_FILE)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    checks = data.get("checks", []) if isinstance(data, dict) else []
    return [c for c in checks if isinstance(c, dict)]


def save_generated_checks(cfg, checks: list[dict]) -> None:
    out = cfg.path(cfg.index_dir)
    out.mkdir(parents=True, exist_ok=True)
    # dedupe by id, last write wins, stable order
    by_id: dict[str, dict] = {}
    for c in checks:
        cid = c.get("id")
        if cid:
            by_id[cid] = c
    payload = {"checks": [by_id[k] for k in sorted(by_id)]}
    _index_path(cfg, GENERATED_CHECKS_FILE).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
