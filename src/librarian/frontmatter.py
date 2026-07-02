"""Frontmatter parsing, serialization, and format-preserving field updates.

Deliberately a minimal-YAML parser, not PyYAML: zero dependencies and — more
importantly — deterministic across machines (an optional PyYAML fallback would
make two clones parse the same doc differently). The grammar covers everything
the librarian schema needs: scalar values, quoted strings, booleans, ISO dates,
inline lists (`[a, "b, c"]`) and block lists (`- item`). Anything outside the
grammar is reported as a warning, never silently dropped.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

_KEY_RE = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")
_BLOCK_ITEM_RE = re.compile(r"^\s+-\s+(.*)$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Canonical field order for serialize(); extras follow alphabetically.
FIELD_ORDER = [
    "id", "title", "domain", "kind", "status", "authority", "source_of_truth",
    "last_verified", "recheck", "read_when", "owner", "tags", "has_disputed_claims",
]

DATE_FIELDS = {"last_verified"}


@dataclass
class ParseResult:
    meta: dict
    warnings: list[str] = field(default_factory=list)
    # (start, end) character offsets of the frontmatter block, including both `---` fences.
    span: tuple[int, int] = (0, 0)


def _strip_comment(value: str) -> str:
    """Strip a trailing ` # comment` from an unquoted value, quote-aware."""
    out, in_s, in_d = [], False, False
    for i, ch in enumerate(value):
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif ch == "#" and not in_s and not in_d:
            if i == 0 or value[i - 1] in " \t":
                break
        out.append(ch)
    return "".join(out).rstrip()


def _unquote(value: str):
    """Coerce a raw scalar: unquote strings, booleans -> bool, everything else -> str.

    No int coercion: ids like `007` and versions like `1.10` must survive round-trips.
    """
    v = value.strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return v[1:-1].replace('\\"', '"')
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        return v[1:-1]
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    return v


def _split_inline_list(inner: str) -> list:
    """Quote-aware comma split of an inline list body (fixes `["a, b", c]`)."""
    items, buf, in_s, in_d = [], [], False, False
    for ch in inner:
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        if ch == "," and not in_s and not in_d:
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    items.append("".join(buf))
    return [_unquote(x) for x in (i.strip() for i in items) if x != ""]


def find_block(text: str) -> tuple[int, int, str] | None:
    """Locate the leading frontmatter block. Returns (start, end, inner) or None.

    `end` is the offset just past the closing fence line (and its newline, if any).
    Unterminated blocks return None — same as no frontmatter.
    """
    if not (text.startswith("---\n") or text.startswith("---\r\n")):
        return None
    first_nl = text.find("\n")
    pos = first_nl + 1
    while True:
        line_end = text.find("\n", pos)
        line = text[pos:] if line_end == -1 else text[pos:line_end]
        if line.rstrip("\r") == "---":
            inner = text[first_nl + 1 : pos]
            end = len(text) if line_end == -1 else line_end + 1
            return (0, end, inner)
        if line_end == -1:
            return None
        pos = line_end + 1


def parse(text: str) -> ParseResult | None:
    """Parse a leading YAML frontmatter block. None if absent or unterminated."""
    block = find_block(text)
    if block is None:
        return None
    _, end, inner = block
    meta: dict = {}
    warnings: list[str] = []
    lines = inner.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip("\r")
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _KEY_RE.match(line)
        if not m:
            if _BLOCK_ITEM_RE.match(line):
                warnings.append(f"line {i + 1}: list item without a preceding `key:` line — ignored")
            else:
                warnings.append(f"line {i + 1}: unsupported YAML ({line.strip()[:60]!r}) — ignored")
            continue
        indent, key, rawval = m.groups()
        if indent:
            warnings.append(f"line {i + 1}: nested mapping under an indent is unsupported — "
                            f"field {key!r} ignored")
            continue
        val = _strip_comment(rawval).strip()
        if val.startswith("[") and val.endswith("]") and len(val) >= 2:
            meta[key] = _split_inline_list(val[1:-1])
        elif val in ("|", ">") or val.startswith(("|", ">")) and len(val) <= 2:
            # Block scalar: consume the indented body so it doesn't spray warnings, but flag it.
            while i < len(lines) and (not lines[i].strip() or lines[i][:1] in " \t"):
                i += 1
            warnings.append(f"line {i}: block scalar (`{val}`) is unsupported — field {key!r} ignored")
        elif val == "":
            # Possible block list.
            items = []
            while i < len(lines):
                bm = _BLOCK_ITEM_RE.match(lines[i].rstrip("\r"))
                if not bm:
                    break
                items.append(_unquote(bm.group(1)))
                i += 1
            if items:
                meta[key] = items
            else:
                meta[key] = ""
        else:
            parsed = _unquote(val)
            if key in DATE_FIELDS and isinstance(parsed, str) and not _valid_date(parsed):
                warnings.append(f"line {i + 1}: {key} {parsed!r} is not a valid YYYY-MM-DD date")
            meta[key] = parsed
    return ParseResult(meta=meta, warnings=warnings, span=(0, end))


def _valid_date(s: str) -> bool:
    if not _ISO_DATE_RE.match(s):
        return False
    try:
        datetime.date.fromisoformat(s)
        return True
    except ValueError:
        return False


def _emit_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "[" + ", ".join(_emit_item(x) for x in v) + "]"
    return _emit_item(v)


def _emit_item(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v)
    if s == "" or any(c in s for c in ":#[]{}\"'") or s != s.strip() or "," in s:
        return '"' + s.replace('"', '\\"') + '"'
    return s


def serialize(meta: dict) -> str:
    """Canonical frontmatter emitter (fixed field order, extras alphabetical)."""
    keys = [k for k in FIELD_ORDER if k in meta]
    keys += sorted(k for k in meta if k not in FIELD_ORDER)
    lines = ["---"] + [f"{k}: {_emit_value(meta[k])}" for k in keys] + ["---", ""]
    return "\n".join(lines)


def set_field(doc_text: str, key: str, value) -> str:
    """Format-preserving single-field update inside the frontmatter block only.

    Replaces the `key:` line if present, else inserts the field before the closing
    fence. The body (which may contain `---` horizontal rules) is never touched.
    Raises ValueError if the document has no frontmatter block.
    """
    block = find_block(doc_text)
    if block is None:
        raise ValueError("document has no frontmatter block")
    start, end, inner = block
    first_nl = doc_text.find("\n")
    emitted = f"{key}: {_emit_value(value)}"
    lines = inner.splitlines(keepends=True)
    out, replaced, i = [], False, 0
    while i < len(lines):
        line = lines[i]
        m = _KEY_RE.match(line.rstrip("\r\n"))
        if m and not m.group(1) and m.group(2) == key and not replaced:
            nl = "\r\n" if line.endswith("\r\n") else "\n"
            out.append(emitted + nl)
            replaced = True
            i += 1
            # Swallow a block list that belonged to the replaced key.
            while i < len(lines) and _BLOCK_ITEM_RE.match(lines[i].rstrip("\r\n")):
                i += 1
            continue
        out.append(line)
        i += 1
    if not replaced:
        out.append(emitted + "\n")
    new_inner = "".join(out)
    closing = doc_text[first_nl + 1 + len(inner) : end]
    return doc_text[: first_nl + 1] + new_inner + closing + doc_text[end:]
