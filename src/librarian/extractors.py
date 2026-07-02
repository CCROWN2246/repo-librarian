"""Extractors: pure functions that reduce a command's stdout to a comparable string.

Spec syntax (the `extract` field of a check):
    scalar                     last cell of the last non-empty line (tab-split)
    regex:<pattern>            first capture group of the first match (MULTILINE)
    json:<dotted.path[0]>      value at a dotted path (with [n] indexes); `.length` = array len
    lines                      count of non-empty stdout lines
    column_present:<name>      "present"/"absent" — <name> is the first whitespace token of a line
    column_absent:<name>       inverse of column_present
    exit_code                  the command's exit code (nonzero is not an error for this one)
"""

from __future__ import annotations

import json
import re


class ExtractError(Exception):
    pass


def _colnames(stdout: str) -> set[str]:
    # SHOW COLUMNS-ish output varies: name-only lines, or "name<tab>type". The first
    # whitespace token of each non-empty line is the column name.
    names = set()
    for line in stdout.splitlines():
        tok = line.strip().split()
        if tok:
            names.add(tok[0])
    return names


def _scalar(stdout: str) -> str:
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    if not lines:
        return ""
    cells = lines[-1].split("\t")
    return cells[-1].strip()


def _json_path(stdout: str, path: str) -> str:
    try:
        cur = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise ExtractError(f"stdout is not JSON: {e}") from e
    if not path:
        raise ExtractError("json: requires a path (e.g. json:data.count)")
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        if part == "length":
            if isinstance(cur, (list, dict, str)):
                cur = len(cur)
                continue
            raise ExtractError(f"json path: cannot take length of {type(cur).__name__}")
        if part.startswith("["):
            if not isinstance(cur, list):
                raise ExtractError(f"json path: {part} on non-array {type(cur).__name__}")
            idx = int(part[1:-1])
            try:
                cur = cur[idx]
            except IndexError as e:
                raise ExtractError(f"json path: index {idx} out of range") from e
        else:
            if not isinstance(cur, dict) or part not in cur:
                raise ExtractError(f"json path: key {part!r} not found")
            cur = cur[part]
    if isinstance(cur, bool):
        return "true" if cur else "false"
    return str(cur)


def extract(spec: str, stdout: str, exit_code: int) -> str:
    if spec == "scalar":
        return _scalar(stdout)
    if spec == "lines":
        return str(sum(1 for ln in stdout.splitlines() if ln.strip()))
    if spec == "exit_code":
        return str(exit_code)
    if spec.startswith("regex:"):
        pattern = spec[len("regex:") :]
        try:
            m = re.search(pattern, stdout, re.MULTILINE)
        except re.error as e:
            raise ExtractError(f"bad regex {pattern!r}: {e}") from e
        if not m:
            return "<no-match>"
        return m.group(1) if m.groups() else m.group(0)
    if spec.startswith("json:"):
        return _json_path(stdout, spec[len("json:") :])
    if spec.startswith("column_present:"):
        name = spec[len("column_present:") :]
        return "present" if name in _colnames(stdout) else "absent"
    if spec.startswith("column_absent:"):
        name = spec[len("column_absent:") :]
        return "absent" if name not in _colnames(stdout) else "present"
    raise ExtractError(f"unknown extractor {spec!r}")
