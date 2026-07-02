import os
import unittest

from helpers import RepoCase
from librarian import config
from librarian.config import ConfigError


class ConfigTests(RepoCase):
    def test_defaults(self):
        cfg = self.cfg()
        self.assertEqual(cfg.index_dir, "_index")
        self.assertEqual(cfg.artifacts_file, "librarian-artifacts.toml")
        self.assertIn(".git", cfg.all_skip_dirs)
        self.assertIn("_index", cfg.all_skip_dirs)
        self.assertTrue(cfg.absence_guard)

    def test_unknown_top_level_key_errors(self):
        self.write(".librarian.toml", "schema_version = 1\n[typo_section]\nx = 1\n")
        with self.assertRaises(ConfigError):
            config.load(self.root)

    def test_unknown_key_in_section_errors(self):
        self.write(".librarian.toml", "schema_version = 1\n[scan]\nskip_dir = ['x']\n")
        with self.assertRaisesRegex(ConfigError, "skip_dir"):
            config.load(self.root)

    def test_bad_fail_on_category(self):
        self.write(".librarian.toml", "schema_version = 1\n[index]\nfail_on = ['nonsense']\n")
        with self.assertRaisesRegex(ConfigError, "nonsense"):
            config.load(self.root)

    def test_check_requires_expect_for_assert(self):
        with self.assertRaisesRegex(ConfigError, "expect"):
            self.cfg("[[verify.checks]]\nid='a'\nkind='assert'\ndoc='d.md'\ncmd='echo hi'\n")

    def test_check_cmd_xor_arg(self):
        with self.assertRaisesRegex(ConfigError, "cmd.*arg|arg.*cmd"):
            self.cfg("[[verify.checks]]\nid='a'\nkind='track'\ndoc='d.md'\n")

    def test_check_duplicate_id(self):
        toml = (
            "[[verify.checks]]\nid='a'\nkind='track'\ndoc='d.md'\ncmd='echo 1'\n"
            "[[verify.checks]]\nid='a'\nkind='track'\ndoc='d.md'\ncmd='echo 2'\n"
        )
        with self.assertRaisesRegex(ConfigError, "duplicate"):
            self.cfg(toml)

    def test_arg_requires_source_template(self):
        with self.assertRaisesRegex(ConfigError, "command template"):
            self.cfg("[[verify.checks]]\nid='a'\nkind='track'\ndoc='d.md'\narg='SELECT 1'\n")

    def test_layer_alias_maps_to_source(self):
        cfg = self.cfg(
            "[verify.sources.raw-db]\ncommand = 'echo {arg}'\n"
            "[[verify.checks]]\nid='a'\nkind='track'\ndoc='d.md'\narg='q'\nlayer='raw-db'\n"
        )
        self.assertEqual(cfg.checks[0].source, "raw-db")

    def test_unsupported_schema_version(self):
        self.write(".librarian.toml", "schema_version = 99\n")
        with self.assertRaisesRegex(ConfigError, "schema_version"):
            config.load(self.root)

    def test_find_root_walks_up(self):
        nested = self.root / "a" / "b"
        nested.mkdir(parents=True)
        self.assertEqual(config.find_root(nested), self.root)

    def test_today_env_override(self):
        self.assertEqual(config.today().isoformat(), self.TODAY)

    def test_today_env_invalid(self):
        os.environ["LIBRARIAN_TODAY"] = "not-a-date"
        with self.assertRaises(ConfigError):
            config.today()


if __name__ == "__main__":
    unittest.main()
