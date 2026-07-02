"""Shared fixtures: build throwaway librarian repos in temp dirs."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from librarian import config  # noqa: E402

MINIMAL_CONFIG = "schema_version = 1\n"

GOOD_DOC = """---
id: {id}
title: {title}
domain: {domain}
status: {status}
last_verified: {last_verified}
recheck: {recheck}
read_when: [{read_when}]
tags: []
---
# {title}

body text
"""


def make_doc(**kw) -> str:
    defaults = dict(
        id="doc-a",
        title="Doc A",
        domain="data",
        status="authoritative",
        last_verified="2026-06-01",
        recheck="90d",
        read_when="a task",
    )
    defaults.update(kw)
    return GOOD_DOC.format(**defaults)


class RepoCase(unittest.TestCase):
    """A test case with a fresh temp repo per test and a frozen clock."""

    TODAY = "2026-07-02"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)
        os.environ["LIBRARIAN_TODAY"] = self.TODAY
        self.addCleanup(os.environ.pop, "LIBRARIAN_TODAY", None)
        self.write(".librarian.toml", MINIMAL_CONFIG)

    def write(self, rel: str, content: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")

    def cfg(self, extra_toml: str = "") -> config.Config:
        if extra_toml:
            existing = self.read(".librarian.toml")
            self.write(".librarian.toml", existing + extra_toml)
        return config.load(self.root)
