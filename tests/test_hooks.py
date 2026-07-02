"""Shell-glue smoke tests (POSIX only — hooks are convenience glue, not engine)."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import SRC  # noqa: F401

from librarian import scaffold

BASH = shutil.which("bash")


@unittest.skipUnless(os.name != "nt" and BASH, "requires bash")
class HookTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        scaffold.init(self.root, agent="both")

    def test_scripts_parse(self):
        for rel in (".githooks/pre-commit", ".claude/hooks/librarian-session.sh"):
            proc = subprocess.run([BASH, "-n", str(self.root / rel)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, f"{rel}: {proc.stderr}")

    def test_hooks_degrade_without_librarian_on_path(self):
        # A teammate without the tool installed must still be able to commit / start sessions.
        env = dict(os.environ, PATH="/usr/bin:/bin")
        subprocess.run(["git", "init", "-q"], cwd=self.root, env=env, check=True)
        for rel in (".githooks/pre-commit", ".claude/hooks/librarian-session.sh"):
            proc = subprocess.run([BASH, str(self.root / rel)], cwd=self.root,
                                  env=env, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, f"{rel} must exit 0 without librarian: "
                             f"{proc.stderr}")

    def test_pre_commit_executable_bit(self):
        self.assertTrue(os.access(self.root / ".githooks" / "pre-commit", os.X_OK))


if __name__ == "__main__":
    unittest.main()
