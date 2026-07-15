#!/usr/bin/env python3
"""Synthetic-corpus fuzzer (Phase B, layer 2) — 'test the crap out of it'.

Builds a deterministic corpus with gen_corpus.build, then applies random
mutations (truncation, frontmatter corruption, deleted references, unicode/binary
injection, duplicate ids, corrupt sidecars, huge bodies) and runs the whole
command matrix, asserting the invariants that must hold on ANY corpus:

  * no command CRASHES — every invocation returns an exit code in {0,1,2},
    never an uncaught exception or a leaked traceback;
  * `index` is deterministic — run-twice on the same files is byte-identical.

Every finding is reported with the seed + round + mutation + command needed to
reproduce it, so it can become a regression test in tests/test_invariants.py.

Deterministic: same --seed -> same mutations -> same result. Headless; no network.

Usage:
    python3 fuzz.py [--seeds 5] [--rounds 4] [--docs 40] [--json]
Exit code: 0 if no findings, 1 if any invariant was violated.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import random
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
for p in (str(SRC), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import gen_corpus  # noqa: E402

from librarian import cli  # noqa: E402

# Read/analysis + apply commands run against whatever corpus state exists. propose
# and archive get randomized inputs below; init mutates and is out of scope.
MATRIX = [
    ["index"],
    ["index", "--check"],
    ["status"],
    ["status", "--hook"],
    ["search", "tender", "rejection"],
    ["verify"],
    ["doctor"],
    ["query"],
    ["query", "pricing"],
    ["todos"],
    ["dream"],
    ["why"],
    ["enrich"],
    ["suggest"],
    ["backfill"],
    ["apply", "--all"],
    ["apply", "--auto"],
    ["ingest"],
]


def run_cmd(root: Path, argv: list[str], stdin_text: str | None = None):
    """Run one command in-process. Returns ('ok', code, out) or ('EXC', traceback, out)."""
    import traceback

    buf = io.StringIO()
    old_stdin = sys.stdin
    if stdin_text is not None:
        sys.stdin = io.StringIO(stdin_text)
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = cli.main([argv[0], "--root", str(root), *argv[1:]])
        return ("ok", code, buf.getvalue())
    except BaseException:
        return ("EXC", traceback.format_exc(), buf.getvalue())
    finally:
        sys.stdin = old_stdin


# ---------------------------- mutators ---------------------------------------
def _md_files(root: Path) -> list[Path]:
    return [p for p in (root / "docs").rglob("*.md")] if (root / "docs").exists() else []


def mut_truncate(root: Path, rng: random.Random) -> str:
    files = _md_files(root)
    if not files:
        return "truncate(noop)"
    f = rng.choice(files)
    data = f.read_bytes()
    f.write_bytes(data[: rng.randint(0, max(1, len(data) // 2))])
    return f"truncate({f.name})"


def mut_corrupt_frontmatter(root: Path, rng: random.Random) -> str:
    files = _md_files(root)
    if not files:
        return "corrupt_fm(noop)"
    f = rng.choice(files)
    f.write_text(
        "---\nid: [unclosed\ntitle: : :\n\ttab: bad\nread_when: {not: a list}\n---\n# x\n", encoding="utf-8"
    )
    return f"corrupt_fm({f.name})"


def mut_delete_referenced(root: Path, rng: random.Random) -> str:
    # delete a file the registry points at, leaving a dangling reference
    reg = root / "librarian-artifacts.toml"
    for cand in ("sql/monthly_revenue_rollup.sql", "sql/fuel_index_load.sql", "data/carrier_master.csv"):
        p = root / cand
        if p.exists():
            p.unlink()
            return f"delete_ref({cand}, registry={reg.exists()})"
    return "delete_ref(noop)"


def mut_inject_binary(root: Path, rng: random.Random) -> str:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    p = root / "docs" / f"binary-{rng.randint(0, 9999)}.md"
    p.write_bytes(bytes(rng.randint(0, 255) for _ in range(64)))
    return f"inject_binary({p.name})"


def mut_inject_unicode(root: Path, rng: random.Random) -> str:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    p = root / "docs" / f"ünï-{rng.randint(0, 9999)}-🚚.md"
    p.write_text(
        "---\nid: ünï\ntitle: café 🚚\ndomain: dätä\nstatus: authoritative\n"
        "last_verified: 2026-06-01\nrecheck: 90d\nread_when: [日本語]\ntags: [café]\n---\n# 🎉 中文\n",
        encoding="utf-8",
    )
    return f"inject_unicode({p.name})"


def mut_duplicate_id(root: Path, rng: random.Random) -> str:
    files = _md_files(root)
    if len(files) < 1:
        return "dup_id(noop)"
    f = rng.choice(files)
    dup = f.with_name(f"dup-{rng.randint(0, 9999)}.md")
    dup.write_text(f.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    return f"dup_id({dup.name})"


def mut_corrupt_sidecar(root: Path, rng: random.Random) -> str:
    idx = root / "_index"
    idx.mkdir(parents=True, exist_ok=True)
    name = rng.choice(
        ["proposals.json", "baselines.json", "provenance.json", "generated-checks.json", "catalog.json"]
    )
    (idx / name).write_text(
        rng.choice(["{ bad json ][", "]]]", "null", "[1,2,", "NOT JSON"]), encoding="utf-8"
    )
    return f"corrupt_sidecar({name})"


def mut_huge_body(root: Path, rng: random.Random) -> str:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    p = root / "docs" / f"huge-{rng.randint(0, 9999)}.md"
    p.write_text(
        "---\nid: huge\ntitle: Huge\ndomain: data\nstatus: authoritative\n"
        "last_verified: 2026-06-01\nrecheck: 90d\nread_when: [big]\ntags: []\n---\n# Huge\n\n"
        + ("word " * 120_000),
        encoding="utf-8",
    )
    return f"huge_body({p.name})"


MUTATORS = [
    mut_truncate,
    mut_corrupt_frontmatter,
    mut_delete_referenced,
    mut_inject_binary,
    mut_inject_unicode,
    mut_duplicate_id,
    mut_corrupt_sidecar,
    mut_huge_body,
]


# ---------------------------- checks -----------------------------------------
def _snapshot_index(root: Path) -> dict:
    idx = root / "_index"
    return {p.name: p.read_bytes() for p in sorted(idx.glob("*")) if p.is_file()} if idx.exists() else {}


def check_matrix(root: Path, rng: random.Random) -> list[dict]:
    findings = []
    # a randomized fix proposal + an archive on a real doc, plus the read matrix
    matrix = list(MATRIX)
    docs = _md_files(root)
    stdins = {}
    if docs:
        rel = docs[rng.randint(0, len(docs) - 1)].relative_to(root).as_posix()
        matrix.append(["archive", rel])
        matrix.append(["propose"])
        stdins[tuple(["propose"])] = json.dumps(
            {"type": "fix", "targets": [{"path": rel}], "action": {"replace": {"old": "the", "new": "THE"}}}
        )
    for argv in matrix:
        kind, code, out = run_cmd(root, argv, stdins.get(tuple(argv)))
        if kind == "EXC":
            findings.append({"kind": "CRASH", "cmd": " ".join(argv), "detail": code.strip().splitlines()[-1]})
        elif code not in (0, 1, 2):
            findings.append({"kind": "BAD_CODE", "cmd": " ".join(argv), "detail": f"exit {code}"})
        elif "Traceback (most recent call last)" in out:
            findings.append({"kind": "TRACE_LEAK", "cmd": " ".join(argv), "detail": "traceback in output"})
    return findings


def check_index_determinism(root: Path) -> list[dict]:
    run_cmd(root, ["index"])
    a = _snapshot_index(root)
    run_cmd(root, ["index"])
    b = _snapshot_index(root)
    diffs = [k for k in set(a) | set(b) if a.get(k) != b.get(k)]
    return [{"kind": "NON_DETERMINISTIC", "cmd": "index x2", "detail": f"changed: {diffs}"}] if diffs else []


def fuzz_seed(seed: int, n_docs: int, rounds: int) -> list[dict]:
    findings = []
    rng = random.Random(seed)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / f"corpus{seed}"
        gen_corpus.build(root, n_docs=n_docs, seed=seed, bare=False)
        # determinism on the pristine, well-formed corpus
        for f in check_index_determinism(root):
            findings.append({**f, "seed": seed, "round": 0, "mutation": "(pristine)"})
        for r in range(1, rounds + 1):
            mut = rng.choice(MUTATORS)
            try:
                label = mut(root, rng)
            except Exception as e:  # a mutator itself blowing up is a harness bug, not a finding
                label = f"{mut.__name__}!ERR:{e}"
            for f in check_matrix(root, rng):
                findings.append({**f, "seed": seed, "round": r, "mutation": label})
            # index must stay deterministic even on a mutated corpus
            for f in check_index_determinism(root):
                findings.append({**f, "seed": seed, "round": r, "mutation": label})
    return findings


def run(seeds: int, rounds: int, n_docs: int, base_seed: int = 1000) -> list[dict]:
    all_findings = []
    for i in range(seeds):
        all_findings.extend(fuzz_seed(base_seed + i, n_docs, rounds))
    return all_findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5, help="number of distinct corpora to fuzz")
    ap.add_argument("--rounds", type=int, default=4, help="mutation rounds per corpus")
    ap.add_argument("--docs", type=int, default=40, help="docs per corpus")
    ap.add_argument("--base-seed", type=int, default=1000)
    ap.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = ap.parse_args()

    findings = run(args.seeds, args.rounds, args.docs, args.base_seed)
    if args.json:
        print(json.dumps(findings, indent=2))
    else:
        combos = args.seeds * (1 + args.rounds)
        print(f"fuzzed {args.seeds} corpora x {args.rounds} mutation rounds ({combos} invariant checkpoints)")
        if not findings:
            print("no invariant violations — clean.")
        else:
            print(f"{len(findings)} FINDING(S):")
            for f in findings:
                print(
                    f"  [{f['kind']}] seed={f['seed']} round={f['round']} mut={f['mutation']} "
                    f"cmd='{f['cmd']}' — {f['detail']}"
                )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
