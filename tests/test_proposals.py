"""Proposal-object schema tests (the compatibility spine).

Covers: id computation + dedup, whole-object round-trip, per-field validation,
schema_version handling, the trust-ladder caps, the generated-checks sidecar +
its config merge, and a golden proposals.json fixture spanning all 8 types.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from helpers import RepoCase
from librarian import config, proposals
from librarian.proposals import ProposalError

GOLDEN = Path(__file__).resolve().parent / "golden" / "proposals.json"


def sample_proposals() -> list[proposals.Proposal]:
    """One proposal per type, fully populated, with fixed (fake) hashes + dates so
    the serialization is deterministic. Regenerate the golden with:

        python3 -c "from tests.test_proposals import sample_proposals; \
from librarian import proposals; \
open('tests/golden/proposals.json','w').write(proposals.dump(sample_proposals()))"
    """
    P = proposals

    def T(path, sha, line=None):
        return P.Target(path=path, base_sha256=sha, line=line)

    dream = P.Provenance(
        source="worklist:open_conflicts", drafted_at="2026-07-08", drafted_by="librarian-dream"
    )
    enrich = P.Provenance(
        source="catalog-gap",
        command="psql -c 'select 1'",
        evidence="3 tables",
        drafted_at="2026-07-08",
        drafted_by="librarian-enrich",
    )
    return [
        P.make(
            "fix",
            [T("docs/schema.md", "a" * 64, 12)],
            {"replace": {"old": "20 stations", "new": "17 stations"}, "drop_marker": True},
            provenance=dream,
            rationale="min dock count is 15, not 20",
        ),
        P.make(
            "ack",
            [T("docs/interview.md", "b" * 64, 8)],
            {"mark": "librarian:ack"},
            provenance=dream,
            rationale="transcript — keep verbatim",
        ),
        P.make(
            "archive",
            [T("docs/old-plan.md", "c" * 64)],
            {
                "to": "_archive/old-plan.md",
                "set_status": "archived",
                "evidence_kind": "shipped_handoff",
                "evidence_ref": "commit abc123",
            },
            provenance=dream,
            rationale="plan shipped in HEAD",
        ),
        P.make(
            "merge",
            [T("docs/a.md", "d" * 64), T("docs/b.md", "e" * 64)],
            {
                "canonical": "docs/a.md",
                "redundant": "docs/b.md",
                "carry_over": ["Section X — unique"],
                "then_archive": True,
            },
            provenance=dream,
            rationale="near-duplicate docs",
        ),
        P.make(
            "set_read_when",
            [T("docs/routing.md", "f" * 64)],
            {"read_when": ["when onboarding", "before touching ETL"]},
            provenance=dream,
            rationale="empty routing phrase",
        ),
        P.make(
            "resolve_absence",
            [T("docs/gaps.md", "1" * 64, 4)],
            {"verdict": "stale_claim", "filled_by": "docs/answer.md"},
            provenance=dream,
            rationale="the catalog actually answers this",
        ),
        P.make(
            "enrich_create",
            [T("docs/ops/backup.md", "")],
            {
                "new_path": "docs/ops/backup.md",
                "domain": "ops",
                "status": "provisional",
                "frontmatter": {
                    "id": "ops-backup",
                    "title": "Backup coverage",
                    "domain": "ops",
                    "status": "provisional",
                },
                "body": "# Backup coverage\n\nprovisional draft\n",
                "spawns_check": "backup_coverage",
            },
            provenance=enrich,
            rationale="gap: no backup-coverage doc",
        ),
        P.make(
            "add_check",
            [T("docs/ops/backup.md", "")],
            {
                "check_id": "backup_coverage",
                "source": "warehouse",
                "check": {
                    "id": "backup_coverage",
                    "source": "warehouse",
                    "kind": "track",
                    "cmd": "echo 3",
                    "extract": "scalar",
                    "doc": "docs/ops/backup.md",
                },
            },
            provenance=enrich,
            rationale="keep the enriched fact honest",
        ),
    ]


class IdTests(unittest.TestCase):
    def test_id_shape(self):
        p = sample_proposals()[0]
        self.assertTrue(p.id.startswith("p_"))
        self.assertEqual(len(p.id), 2 + 12)

    def test_id_dedupes_across_redraft(self):
        # Same logical fix, different base_sha256 + different corrected text -> same id.
        t1 = proposals.Target(path="docs/x.md", base_sha256="a" * 64, line=3)
        t2 = proposals.Target(path="docs/x.md", base_sha256="z" * 64, line=99)
        p1 = proposals.make("fix", [t1], {"replace": {"old": "WRONG", "new": "right"}})
        p2 = proposals.make("fix", [t2], {"replace": {"old": "WRONG", "new": "RIGHT-v2"}})
        self.assertEqual(p1.id, p2.id)

    def test_id_differs_on_different_old_text(self):
        t = proposals.Target(path="docs/x.md", base_sha256="a" * 64)
        p1 = proposals.make("fix", [t], {"replace": {"old": "A", "new": "B"}})
        p2 = proposals.make("fix", [t], {"replace": {"old": "C", "new": "B"}})
        self.assertNotEqual(p1.id, p2.id)

    def test_id_order_independent_targets(self):
        a = proposals.Target(path="docs/a.md", base_sha256="1" * 64)
        b = proposals.Target(path="docs/b.md", base_sha256="2" * 64)
        act = {"canonical": "docs/a.md", "redundant": "docs/b.md"}
        self.assertEqual(
            proposals.make("merge", [a, b], act).id,
            proposals.make("merge", [b, a], act).id,
        )


class RoundTripTests(unittest.TestCase):
    def test_every_type_round_trips(self):
        for p in sample_proposals():
            with self.subTest(type=p.type):
                back = proposals.from_dict(p.to_dict())
                self.assertEqual(back.id, p.id)
                self.assertEqual(back.to_dict(), p.to_dict())

    def test_schema_version_is_stamped(self):
        self.assertEqual(sample_proposals()[0].to_dict()["schema_version"], "1")


class ValidationTests(unittest.TestCase):
    def _base(self) -> dict:
        return sample_proposals()[0].to_dict()

    def test_unknown_top_key_rejected(self):
        d = self._base()
        d["surprise"] = 1
        with self.assertRaises(ProposalError):
            proposals.from_dict(d)

    def test_bad_schema_version_rejected(self):
        d = self._base()
        d["schema_version"] = "2"
        with self.assertRaises(ProposalError):
            proposals.from_dict(d)

    def test_bad_type_rejected(self):
        d = self._base()
        d["type"] = "nuke"
        with self.assertRaises(ProposalError):
            proposals.from_dict(d)

    def test_empty_targets_rejected(self):
        d = self._base()
        d["targets"] = []
        with self.assertRaises(ProposalError):
            proposals.from_dict(d)

    def test_tampered_id_rejected(self):
        d = self._base()
        d["id"] = "p_000000000000"
        with self.assertRaises(ProposalError):
            proposals.from_dict(d)

    def test_base_sha_change_keeps_id_valid(self):
        # Changing only base_sha256 must NOT invalidate the id (it's excluded).
        d = self._base()
        d["targets"][0]["base_sha256"] = "9" * 64
        d.pop("id")  # recompute
        p = proposals.from_dict(d)
        self.assertEqual(p.id, sample_proposals()[0].id)

    def test_bad_writes_to_rejected(self):
        d = self._base()
        d["risk"]["writes_to"] = "prod"
        with self.assertRaises(ProposalError):
            proposals.from_dict(d)

    def test_unknown_risk_key_rejected(self):
        d = self._base()
        d["risk"]["yolo"] = True
        with self.assertRaises(ProposalError):
            proposals.from_dict(d)


class TrustLadderTests(unittest.TestCase):
    def test_caps(self):
        by_type = {p.type: p for p in sample_proposals()}
        self.assertEqual(proposals.cap_tier(by_type["fix"]), "branch")  # irreversible text edit
        self.assertEqual(proposals.cap_tier(by_type["merge"]), "branch")
        self.assertEqual(proposals.cap_tier(by_type["archive"]), "branch")
        self.assertEqual(proposals.cap_tier(by_type["enrich_create"]), "branch")  # generative
        self.assertEqual(proposals.cap_tier(by_type["ack"]), "commit")
        self.assertEqual(proposals.cap_tier(by_type["add_check"]), "commit")

    def test_main_writes_capped_off(self):
        p = sample_proposals()[1]  # ack
        p.risk.writes_to = "main"
        self.assertEqual(proposals.cap_tier(p), "off")

    def test_effective_tier_is_min(self):
        fix = sample_proposals()[0]
        self.assertEqual(proposals.effective_tier(fix, "commit"), "branch")  # capped
        self.assertEqual(proposals.effective_tier(fix, "off"), "off")
        ack = sample_proposals()[1]
        self.assertEqual(proposals.effective_tier(ack, "commit"), "commit")
        self.assertEqual(proposals.effective_tier(ack, "branch"), "branch")


class GoldenTests(unittest.TestCase):
    def test_matches_golden(self):
        got = proposals.dump(sample_proposals())
        expected = GOLDEN.read_text(encoding="utf-8")
        self.assertEqual(
            got,
            expected,
            "proposals.json golden drifted — if deliberate, regenerate it "
            "(recipe in sample_proposals' docstring)",
        )

    def test_golden_loads_back_to_eight_types(self):
        data = json.loads(GOLDEN.read_text(encoding="utf-8"))
        loaded = [proposals.from_dict(p) for p in data["proposals"]]
        self.assertEqual({p.type for p in loaded}, set(proposals.TYPES))


class SidecarAndConfigTests(RepoCase):
    def test_generated_checks_round_trip(self):
        cfg = self.cfg()
        checks = [
            {"id": "c2", "kind": "track", "cmd": "echo 2", "doc": "d.md"},
            {"id": "c1", "kind": "track", "cmd": "echo 1", "doc": "d.md"},
        ]
        proposals.save_generated_checks(cfg, checks)
        back = proposals.load_generated_checks(cfg)
        self.assertEqual([c["id"] for c in back], ["c1", "c2"])  # sorted, deduped

    def test_config_merges_sidecar_checks(self):
        cfg = self.cfg()
        proposals.save_generated_checks(
            cfg, [{"id": "gen_x", "kind": "track", "cmd": "echo 5", "doc": "d.md"}]
        )
        merged = config.load(self.root)
        self.assertIn("gen_x", {c.id for c in merged.checks})

    def test_human_check_wins_over_generated(self):
        self.write(
            ".librarian.toml",
            "schema_version = 1\n[[verify.checks]]\nid='dup'\nkind='assert'\n"
            "doc='d.md'\ncmd='echo human'\nexpect='human'\n",
        )
        cfg = config.load(self.root)
        proposals.save_generated_checks(
            cfg, [{"id": "dup", "kind": "track", "cmd": "echo machine", "doc": "d.md"}]
        )
        merged = config.load(self.root)
        dup = [c for c in merged.checks if c.id == "dup"]
        self.assertEqual(len(dup), 1)
        self.assertEqual(dup[0].kind, "assert")  # the human TOML one

    def test_malformed_generated_check_skipped(self):
        cfg = self.cfg()
        proposals.save_generated_checks(
            cfg,
            [
                {"id": "ok", "kind": "track", "cmd": "echo 1", "doc": "d.md"},
                {"id": "bad", "kind": "nonsense"},
            ],
        )
        merged = config.load(self.root)
        ids = {c.id for c in merged.checks}
        self.assertIn("ok", ids)
        self.assertNotIn("bad", ids)

    def test_automation_tiers_parse(self):
        cfg = self.cfg("\n[automation]\nfix = 'off'\nack = 'branch'\n")
        self.assertEqual(cfg.tier_for("ack"), "branch")
        self.assertEqual(cfg.tier_for("fix"), "off")
        self.assertEqual(cfg.tier_for("archive"), "off")  # default

    def test_automation_unknown_type_rejected(self):
        with self.assertRaises(config.ConfigError):
            self.cfg("\n[automation]\nnope = 'off'\n")

    def test_automation_bad_tier_rejected(self):
        with self.assertRaises(config.ConfigError):
            self.cfg("\n[automation]\nfix = 'yolo'\n")

    def test_enrich_ttl_parse(self):
        cfg = self.cfg("\n[enrich]\nprovisional_ttl_days = 7\n")
        self.assertEqual(cfg.enrich_provisional_ttl_days, 7)


if __name__ == "__main__":
    unittest.main()
