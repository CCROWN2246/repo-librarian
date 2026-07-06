#!/usr/bin/env python3
"""Generate a synthetic knowledge-repo corpus for benchmarking repo-librarian.

Builds a fake long-running company project ("Meridian Logistics" — a freight
SaaS) at the scale the tool targets (~200 knowledge files), with the failure
modes the librarian exists to beat PLANTED deliberately:

  T1 locate-distinctive   a doc findable by a distinctive term (grep's best case
                          — the honest control where we expect ~parity)
  T2 common-term routing  the authoritative doc for a hot term is NOT the doc
                          that mentions it most (distractor docs planted)
  T3 stale-fact trap      a plausible narrative doc carries an outdated number;
                          the authoritative doc + verify baseline hold the truth
  T4 absence claim        a strategy doc confidently says a source is "TBD"
                          while the source doc sits in the corpus
  T5 artifact routing     the answer lives in a registered SQL/CSV, reachable
                          via the registry's read_when
  T6 provisional flag     a metric doc is status: provisional — reporting it as
                          final is the wrong answer
  T7 quarantined claim    a transcript's false claim wears a KB-CONTRADICTED
                          marker; repeating it as fact is the wrong answer

Deterministic: same --seed -> byte-identical corpus. Ground truth for scoring
is written to <out>/../ground_truth.json (OUTSIDE the corpus so agents can't
read it).

Usage:
    python3 gen_corpus.py --out /tmp/bench/corpus [--docs 200] [--seed 7] [--bare]

--bare writes the same corpus WITHOUT librarian assets (no _index/, no
AGENTS.md, no .librarian.toml) — the baseline condition.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

DOMAINS = ["operations", "data-platform", "product", "finance", "vendors", "reference"]

TOPICS = [
    ("carrier scorecards", "how carriers are graded"),
    ("lane pricing", "pricing freight lanes"),
    ("dock scheduling", "warehouse dock appointments"),
    ("fuel surcharges", "computing fuel surcharge"),
    ("claims handling", "damaged freight claims"),
    ("tender rejections", "why tenders get rejected"),
    ("driver onboarding", "onboarding new drivers"),
    ("route optimization", "optimizing delivery routes"),
    ("invoice auditing", "auditing carrier invoices"),
    ("capacity forecasting", "forecasting trucking capacity"),
    ("customs paperwork", "cross-border customs docs"),
    ("cold chain", "temperature-controlled freight"),
    ("detention fees", "driver detention billing"),
    ("pallet standards", "pallet specs and standards"),
    ("emissions reporting", "freight emissions accounting"),
    ("customer QBRs", "quarterly business reviews"),
    ("SLA definitions", "delivery SLA definitions"),
    ("EDI integration", "EDI message handling"),
    ("spot market", "spot market buying"),
    ("warehouse slotting", "warehouse slotting logic"),
]

FILLER = (
    "Context gathered from ops reviews. {a} interacts with {b} during peak season, and the "
    "handoff is owned by the regional team. Escalations route through the duty manager. "
    "Historical incidents are archived in the ops log. See the runbook for the standard "
    "checklist; exceptions need a supervisor sign-off. Metrics roll up weekly."
)

FM = """---
id: {id}
title: {title}
domain: {domain}
status: {status}
authority: {authority}
last_verified: {lv}
recheck: {recheck}
read_when: [{read_when}]
owner: {owner}
tags: [{tags}]
---
"""


def fm(**kw) -> str:
    defaults = dict(
        status="authoritative", authority="curated", lv="2026-06-15", recheck="90d", owner="ops", tags=""
    )
    defaults.update(kw)
    return FM.format(**defaults)


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def build(out: Path, n_docs: int, seed: int, bare: bool) -> dict:
    rng = random.Random(seed)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # ---------- planted, load-bearing docs (the tasks point here) ----------
    # T1: distinctive term
    write(
        out,
        "docs/operations/dock-scheduling-runbook.md",
        fm(
            id="dock-scheduling-runbook",
            title="Dock scheduling runbook",
            domain="operations",
            read_when="book a dock appointment, dock overbooked, zebra-window rules",
            owner="maria",
        )
        + "# Dock scheduling runbook\n\nThe **zebra-window** rule: docks 1-4 alternate 30-minute "
        "inbound/outbound windows after 14:00. Overbooking beyond 2 slots requires the duty "
        "manager. Cutoff for same-day changes is 11:00 local.\n",
    )

    # T2: authoritative definition of "tender rejection rate" (mentions term ~3x)
    write(
        out,
        "docs/data-platform/metrics-reference.md",
        fm(
            id="metrics-reference",
            title="Metrics reference — canonical definitions",
            domain="data-platform",
            authority="verified",
            lv="2026-06-28",
            recheck="30d",
            read_when="write a metrics query, define a metric, tender rejection rate definition",
            owner="dana",
        )
        + "# Metrics reference\n\n## Tender rejection rate\n"
        "Numerator: tenders declined by the carrier within the response window. Denominator: "
        "all tenders SENT (not booked loads). Excludes auto-expired tenders. Grain: lane-week.\n\n"
        "## On-time delivery\nArrival within the SLA window at the FINAL stop only.\n\n"
        "## Active carrier count\nCarriers with >=1 accepted tender in the trailing 60 days: "
        "412 as of 2026-06.\n\n## Backup-carrier coverage\n61% of lanes (2026-06).\n",
    )

    # T2 distractors: mention "tender rejection" MANY times, define nothing.
    # ops-allhands-notes also carries a stale-carrier-count ECHO (drift propagates).
    for i, (name, blurb) in enumerate(
        [
            ("qbr-talk-track", "QBR talk track"),
            ("ops-allhands-notes", "Ops all-hands notes"),
            ("carrier-newsletter", "Carrier newsletter draft"),
        ]
    ):
        body = "\n".join(
            f"Slide {j}: tender rejection trends — tender rejections were discussed; "
            "tender rejection anecdotes from the field."
            for j in range(1, 8 + i)
        )
        if name == "ops-allhands-notes":
            body += "\n\nQuick numbers: carrier base holding around 379 active carriers."
        write(
            out,
            f"docs/product/{name}.md",
            fm(
                id=name,
                title=blurb,
                domain="product",
                status="reference",
                read_when="prep customer-facing narrative",
                owner="sam",
            )
            + f"# {blurb}\n\n{body}\n",
        )

    # T3 echo, FRESHER-dated than the authoritative metrics doc: recency picks wrong.
    write(
        out,
        "docs/product/june-sales-onepager.md",
        fm(
            id="june-sales-onepager",
            title="June sales one-pager",
            domain="product",
            status="reference",
            lv="2026-06-30",
            recheck="180d",
            read_when="sales collateral, customer-facing numbers",
            owner="sam",
        )
        + "# June sales one-pager\n\nMeridian now serves nearly 380 active carriers with "
        "coverage in all three regions. Spot desk volumes doubled YoY.\n",
    )

    # T3: stale-fact trap — narrative doc says 379, verified truth is 412
    write(
        out,
        "docs/product/investor-update-may.md",
        fm(
            id="investor-update-may",
            title="Investor update narrative (May)",
            domain="product",
            status="reference",
            lv="2026-05-02",
            recheck="180d",
            read_when="investor narrative, growth story",
            owner="sam",
        )
        + "# Investor update narrative (May)\n\nWe now work with 379 active carriers across 3 "
        "regions, up 12% QoQ. Momentum in the spot desk continues.\n",
    )

    # T4: absence claim — strategy doc says fuel index source TBD; the source doc EXISTS
    write(
        out,
        "docs/finance/pricing-strategy.md",
        fm(
            id="pricing-strategy",
            title="Lane pricing strategy",
            domain="finance",
            status="provisional",
            read_when="pricing strategy, margin targets",
            owner="lee",
        )
        + "# Lane pricing strategy\n\nMargin floor 14%. Fuel-index source: TBD — not yet "
        "identified, pending vendor selection.\n",
    )
    write(
        out,
        "docs/finance/fuel-index-source.md",
        fm(
            id="fuel-index-source",
            title="Fuel index source of record",
            domain="finance",
            authority="verified",
            lv="2026-06-20",
            recheck="60d",
            read_when="fuel surcharge input, which fuel index we use",
            owner="lee",
        )
        + "# Fuel index source of record\n\nWe use the **DOE weekly diesel index (PADD-level)**, "
        "ingested Mondays via `sql/fuel_index_load.sql`. Contracted through 2027.\n",
    )

    # T6: provisional metric — the signal lives in FRONTMATTER ONLY (status: provisional);
    # the body reads like any other number. This is the realistic case.
    write(
        out,
        "docs/finance/vendor-spend.md",
        fm(
            id="vendor-spend",
            title="Vendor spend rollup",
            domain="finance",
            status="provisional",
            read_when="vendor spend, procurement reporting",
            owner="lee",
        )
        + "# Vendor spend rollup\n\nQ2 vendor spend: $4.1M across 63 vendors. An accruals "
        "dispute with two vendors remains open with procurement.\n",
    )

    # T8: verify-only fact — the current value lives in NO doc, only the live warehouse.
    write(
        out,
        "docs/operations/claims-backlog.md",
        fm(
            id="claims-backlog",
            title="Claims backlog — reporting note",
            domain="operations",
            read_when="claims backlog number, quote the backlog",
            owner="maria",
        )
        + "# Claims backlog — reporting note\n\nThe open-claims backlog moves daily; never "
        "quote yesterday's number. Pull it live before citing.\n",
    )

    # T7: quarantined transcript claim
    write(
        out,
        "docs/vendors/carrier-council-transcript.md",
        fm(
            id="carrier-council-transcript",
            title="Carrier council transcript (raw)",
            domain="vendors",
            status="reference",
            authority="unverified",
            recheck="365d",
            read_when="carrier sentiment, council history",
            owner="sam",
        )
        + "# Carrier council transcript (raw)\n\n> Intake note: non-technical speakers; "
        'authority: unverified.\n\n"Every lane has a dedicated backup carrier assigned." '
        "<!-- KB-CONTRADICTED: conflicts with [verified: backup coverage is 61% of lanes, "
        "metrics-reference]; retained for context, not fact -->\n\n"
        '"Detention billing kicks in after two hours everywhere."\n',
    )

    # T5: artifact answers
    write(
        out,
        "sql/monthly_revenue_rollup.sql",
        "-- Monthly revenue rollup per customer.\n-- Grain: one row per customer-month; "
        "excludes disputed invoices.\nSELECT customer_id, month, sum(net) FROM invoices "
        "GROUP BY 1, 2;\n",
    )
    write(
        out,
        "sql/fuel_index_load.sql",
        "-- Load the DOE weekly diesel index (PADD level) into fuel_index.\nINSERT INTO "
        "fuel_index SELECT * FROM staging_doe;\n",
    )
    write(
        out,
        "data/carrier_master.csv",
        "carrier_id,name,region,active\n"
        + "\n".join(
            f"C{i:04d},Carrier {i},{rng.choice(['east', 'central', 'west'])},{1 if i % 7 else 0}"
            for i in range(1, 61)
        )
        + "\n",
    )
    write(
        out,
        "scripts/refresh_scorecards.py",
        '"""Refresh carrier scorecards from the warehouse (runs Mondays)."""\nprint("ok")\n',
    )

    registry = """# librarian-artifacts.toml
[[artifact]]
path = "sql/monthly_revenue_rollup.sql"
id = "monthly-revenue-rollup"
title = "Monthly revenue rollup per customer"
domain = "finance"
kind = "sql"
status = "authoritative"
last_verified = "2026-06-18"
read_when = ["compute monthly revenue", "revenue rollup grain", "trace a revenue number"]
desc = "Grain: customer-month; excludes disputed invoices."

[[artifact]]
path = "sql/fuel_index_load.sql"
id = "fuel-index-load"
title = "Fuel index loader (DOE weekly diesel)"
domain = "finance"
kind = "sql"
status = "authoritative"
last_verified = "2026-06-20"
read_when = ["fuel index ingestion", "where fuel data comes from"]

[[artifact]]
path = "data/carrier_master.csv"
id = "carrier-master-csv"
title = "Carrier master export"
domain = "data-platform"
kind = "csv"
status = "reference"
last_verified = "2026-06-10"
read_when = ["carrier lookup without the warehouse"]
source_of_truth = "sql/monthly_revenue_rollup.sql"

[[artifact]]
path = "scripts/refresh_scorecards.py"
id = "refresh-scorecards"
title = "Carrier scorecard refresh job"
domain = "operations"
kind = "script"
status = "authoritative"
last_verified = "2026-06-18"
read_when = ["scorecards stale", "refresh carrier grades"]
"""
    write(out, "librarian-artifacts.toml", registry)

    # ---------- filler docs to reach n_docs (realistic bulk) ----------
    planted = 10  # md docs written above
    owners = ["maria", "dana", "sam", "lee", "ops"]
    for i in range(max(0, n_docs - planted)):
        topic, blurb = TOPICS[i % len(TOPICS)]
        dom = DOMAINS[i % len(DOMAINS)]
        slug = f"{topic.replace(' ', '-')}-{i:03d}"
        a, b = rng.sample([t for t, _ in TOPICS], 2)
        body = FILLER.format(a=a, b=b)
        write(
            out,
            f"docs/{dom}/{slug}.md",
            fm(
                id=slug,
                title=f"{blurb.capitalize()} — note {i:03d}",
                domain=dom,
                status=rng.choice(["authoritative"] * 3 + ["reference"] * 2 + ["provisional"]),
                lv=f"2026-0{rng.randint(3, 6)}-{rng.randint(10, 28)}",
                recheck=rng.choice(["60d", "90d", "180d"]),
                read_when=f"{blurb}, {topic} questions",
                owner=rng.choice(owners),
                tags=topic.split()[0],
            )
            + f"# {blurb.capitalize()} — note {i:03d}\n\n{body}\n",
        )

    config = """schema_version = 1
[taxonomy]
domains = ["operations", "data-platform", "product", "finance", "vendors", "reference"]
[verify]
default_timeout = 30
[verify.sources.warehouse]
command = "python3 warehouse/query.py {arg}"

[[verify.checks]]
id = "active_carrier_count"
kind = "track"
doc = "docs/data-platform/metrics-reference.md"
source = "warehouse"
arg = "SELECT count(*) FROM carriers WHERE active = 1"
extract = "scalar"

[[verify.checks]]
id = "open_claims_backlog"
kind = "track"
doc = "docs/operations/claims-backlog.md"
source = "warehouse"
arg = "SELECT count(*) FROM claims WHERE status = 'open'"
extract = "scalar"
"""
    write(out, ".librarian.toml", config)
    write(
        out,
        "warehouse/query.py",
        '"""Fake warehouse for the benchmark: answers the tracked queries."""\n'
        "import sys\n"
        "q = sys.argv[1]\n"
        'print(412 if "carriers" in q else 93 if "claims" in q else 0)\n',
    )
    # the claims baseline is deliberately STALE (87) — the live number (93) exists
    # only in the warehouse; quoting the baseline without a live pull is the trap.
    write(
        out,
        "_index/baselines.json",
        '{\n  "active_carrier_count": {\n    "recorded": "2026-06-28",\n    "value": "412"\n  },\n'
        '  "open_claims_backlog": {\n    "recorded": "2026-06-20",\n    "value": "87"\n  }\n}\n',
    )

    if bare:
        # baseline condition: strip everything librarian adds
        for rel in (".librarian.toml", "librarian-artifacts.toml", "_index"):
            target = out / rel
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
    else:
        # index the corpus with the real tool + scaffold the agent block
        repo_src = Path(__file__).resolve().parent.parent / "src"
        env_path = f"{repo_src}"
        subprocess.run(
            [sys.executable, "-m", "librarian.cli", "index", "--root", str(out), "--quiet"],
            env={"PYTHONPATH": env_path, "PATH": "/usr/bin:/bin", "LIBRARIAN_TODAY": "2026-07-01"},
            check=True,
        )
        agents_block = Path(__file__).resolve().parent.parent / "src/librarian/assets/AGENTS_BLOCK.md"
        write(out, "AGENTS.md", agents_block.read_text(encoding="utf-8"))

    truth = {
        "T1": {
            "answer_must_mention": ["zebra-window", "duty manager"],
            "doc": "docs/operations/dock-scheduling-runbook.md",
        },
        "T2": {
            "answer_must_mention": ["tenders SENT", "lane-week"],
            "doc": "docs/data-platform/metrics-reference.md",
            "wrong_if_only": ["qbr-talk-track", "ops-allhands-notes", "carrier-newsletter"],
        },
        "T3": {
            "answer_must_mention": ["412"],
            "stale_wrong": "379 / nearly 380",
            "echoes": ["investor-update-may", "june-sales-onepager (FRESHER-dated)", "ops-allhands-notes"],
            "doc": "docs/data-platform/metrics-reference.md",
        },
        "T4": {
            "answer_must_mention": ["DOE"],
            "wrong": "TBD / not identified",
            "doc": "docs/finance/fuel-index-source.md",
        },
        "T5": {
            "answer_must_mention": ["customer-month", "disputed"],
            "doc": "sql/monthly_revenue_rollup.sql",
        },
        "T6": {
            "answer_must_mention": ["provisional"],
            "wrong": "reported as final",
            "note": "signal is frontmatter-only in v2",
            "doc": "docs/finance/vendor-spend.md",
        },
        "T7": {
            "answer_must_mention": ["61%"],
            "stale_wrong": "every lane has a dedicated backup",
            "doc": "docs/vendors/carrier-council-transcript.md",
        },
        "T8": {
            "answer_must_mention": ["93"],
            "stale_wrong": "87 (stale baseline) or any doc number",
            "note": "verify-only: live warehouse holds the truth",
            "doc": "docs/operations/claims-backlog.md",
        },
    }
    (out.parent / f"ground_truth_{out.name}.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    return truth


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--docs", type=int, default=200, help="total .md knowledge docs (default 200)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--bare", action="store_true", help="baseline condition: no librarian assets")
    args = ap.parse_args()
    build(args.out, args.docs, args.seed, args.bare)
    n = sum(1 for _ in args.out.rglob("*") if _.is_file())
    print(f"corpus at {args.out}: {n} files ({'bare' if args.bare else 'librarian-enabled'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
