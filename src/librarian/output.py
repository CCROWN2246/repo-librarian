"""Reporter: human text vs --json vs --quiet.

ASCII status tags (no emoji): deterministic, greppable, Windows-console-safe.
In --json mode exactly one JSON document goes to stdout; human chatter goes to
stderr so `librarian ... --json | jq` always works.
"""

from __future__ import annotations

import json
import sys


class Reporter:
    def __init__(self, *, as_json: bool = False, quiet: bool = False):
        self.as_json = as_json
        self.quiet = quiet

    def say(self, msg: str = "") -> None:
        """Normal human output (suppressed by --quiet; redirected to stderr in --json)."""
        if self.quiet:
            return
        print(msg, file=sys.stderr if self.as_json else sys.stdout)

    def warn(self, msg: str) -> None:
        print(f"warn: {msg}", file=sys.stderr)

    def error(self, msg: str) -> None:
        print(f"error: {msg}", file=sys.stderr)

    def emit_json(self, payload) -> None:
        print(json.dumps(payload, indent=2, sort_keys=True))


def tag(status: str) -> str:
    return f"[{status}]".ljust(9)
