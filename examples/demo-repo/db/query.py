#!/usr/bin/env python3
"""Run one SQL query against the demo database (seed.sql loaded into :memory:).

Used by the [[verify.checks]] in .librarian.toml:
    python3 db/query.py "SELECT count(*) FROM stations"
Prints rows tab-separated, one per line — the shape librarian's `scalar` and
`column_*` extractors expect. Stdlib only, nothing to install.
"""

import sqlite3
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: query.py <sql>", file=sys.stderr)
        return 2
    seed = Path(__file__).resolve().parent / "seed.sql"
    conn = sqlite3.connect(":memory:")
    conn.executescript(seed.read_text(encoding="utf-8"))
    for row in conn.execute(sys.argv[1]):
        print("\t".join("" if v is None else str(v) for v in row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
