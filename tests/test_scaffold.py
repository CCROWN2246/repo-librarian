import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from helpers import SRC  # noqa: F401
from librarian import scaffold


def tree_hash(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".git" not in p.parts:
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class ScaffoldCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)


class InitTests(ScaffoldCase):
    def test_init_twice_zero_diff(self):
        scaffold.init(self.root, agent="both")
        first = tree_hash(self.root)
        report = scaffold.init(self.root, agent="both")
        self.assertEqual(tree_hash(self.root), first)
        self.assertEqual(report.written, [])
        self.assertEqual(report.updated, [])

    def test_init_writes_expected_set(self):
        scaffold.init(self.root, agent="both")
        for rel in (".librarian.toml", "librarian-artifacts.toml", "KNOWLEDGE_PROTOCOL.md",
                    "docs/NAVIGATOR.md", "_inbox/README.md", "_archive/README.md",
                    ".githooks/pre-commit", "AGENTS.md", "CLAUDE.md",
                    ".claude/commands/kb.md", ".claude/hooks/librarian-session.sh",
                    ".claude/settings.json", "_index/.scaffold.json"):
            self.assertTrue((self.root / rel).exists(), rel)

    def test_agent_none_skips_glue(self):
        scaffold.init(self.root, agent="none")
        self.assertFalse((self.root / "AGENTS.md").exists())
        self.assertFalse((self.root / ".claude").exists())

    def test_existing_agents_md_content_preserved(self):
        (self.root / "AGENTS.md").write_text("# My rules\n\nDo not touch.\n", encoding="utf-8")
        scaffold.init(self.root, agent="agents-md")
        text = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Do not touch.", text)
        self.assertIn(scaffold.MARKER_BEGIN, text)
        scaffold.init(self.root, agent="agents-md")   # still exactly one block
        text2 = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(text2.count(scaffold.MARKER_BEGIN), 1)
        self.assertEqual(text, text2)

    def test_settings_merge_preserves_user_keys(self):
        claude = self.root / ".claude"
        claude.mkdir()
        (claude / "settings.json").write_text(json.dumps({
            "permissions": {"allow": ["Bash(ls:*)"]},
            "hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [
                {"type": "command", "command": "bash mine.sh"}]}]},
        }), encoding="utf-8")
        scaffold.init(self.root, agent="claude")
        settings = json.loads((claude / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(settings["permissions"]["allow"], ["Bash(ls:*)"])
        self.assertEqual(settings["hooks"]["PostToolUse"][0]["hooks"][0]["command"], "bash mine.sh")
        self.assertTrue(any(scaffold.HOOK_COMMAND in json.dumps(e)
                            for e in settings["hooks"]["SessionStart"]))

    def test_init_never_overwrites_modified_config(self):
        scaffold.init(self.root)
        cfg = self.root / ".librarian.toml"
        cfg.write_text("schema_version = 1\n# customized\n", encoding="utf-8")
        scaffold.init(self.root)
        self.assertIn("# customized", cfg.read_text(encoding="utf-8"))


class UpgradeTests(ScaffoldCase):
    def test_upgrade_refreshes_unmodified_keeps_modified(self):
        scaffold.init(self.root, agent="both")
        protocol = self.root / "KNOWLEDGE_PROTOCOL.md"
        hook = self.root / ".githooks" / "pre-commit"
        protocol.write_text("MY EDITED PROTOCOL\n", encoding="utf-8")
        # simulate an older scaffolded hook that the manifest still owns
        manifest_path = self.root / "_index" / ".scaffold.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        old_hook = "#!/bin/sh\nold version\n"
        hook.write_text(old_hook, encoding="utf-8", newline="\n")
        # hash the STRING (what the engine compares after text-mode read), not raw
        # disk bytes — on Windows those differ by CRLF translation
        manifest["files"][".githooks/pre-commit"] = scaffold._sha(old_hook)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        report = scaffold.init(self.root, agent="both", upgrade=True)
        self.assertIn("KNOWLEDGE_PROTOCOL.md", report.kept)          # user-modified: untouched
        self.assertEqual(protocol.read_text(encoding="utf-8"), "MY EDITED PROTOCOL\n")
        self.assertIn(".githooks/pre-commit", report.updated)        # ours: refreshed
        self.assertNotIn("old version", hook.read_text(encoding="utf-8"))


class UninstallTests(ScaffoldCase):
    def test_uninstall_removes_ours_keeps_config_and_user_content(self):
        (self.root / "AGENTS.md").write_text("# Mine\n", encoding="utf-8")
        scaffold.init(self.root, agent="both")
        report = scaffold.uninstall(self.root)
        self.assertFalse((self.root / "KNOWLEDGE_PROTOCOL.md").exists())
        self.assertFalse((self.root / ".claude" / "commands" / "kb.md").exists())
        self.assertTrue((self.root / ".librarian.toml").exists())
        self.assertTrue((self.root / "librarian-artifacts.toml").exists())
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("# Mine", agents)
        self.assertNotIn(scaffold.MARKER_BEGIN, agents)
        self.assertTrue(report.removed)


class BlockHelperTests(unittest.TestCase):
    def test_upsert_then_strip_roundtrip(self):
        text = "# Head\n"
        with_block = scaffold.upsert_block(text, "content v1")
        self.assertIn("content v1", with_block)
        replaced = scaffold.upsert_block(with_block, "content v2")
        self.assertNotIn("content v1", replaced)
        self.assertEqual(replaced.count(scaffold.MARKER_BEGIN), 1)
        self.assertEqual(scaffold.strip_block(replaced).strip(), "# Head")

    def test_strip_no_block_is_noop(self):
        self.assertEqual(scaffold.strip_block("plain\n"), "plain\n")


if __name__ == "__main__":
    unittest.main()
