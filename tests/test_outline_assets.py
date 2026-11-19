"""Task 6: outline/ledger asset templates and the outline-schema reference.

The schema doc must REFERENCE the canonical paper-writer files (L0-L4 table,
Rung 1/2/3) instead of restating their definition tables, and must mark
``lit_strategy`` as our extension (upstream lacks it; vendor-notices 二.5).
"""
import json
from pathlib import Path

import ledger_audit

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "paper-orchestrator"
ASSETS = SKILL / "assets"


def test_outline_template_keys():
    data = json.loads(
        (ASSETS / "outline_template.json").read_text(encoding="utf-8")
    )
    assert {"title", "venue", "sections", "lit_strategy", "viz_plan"} <= set(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["venue"], str) and data["venue"]
    assert isinstance(data["sections"], list) and data["sections"]
    for sec in data["sections"]:
        assert {"id", "kind", "claims", "purpose"} <= set(sec)
        assert isinstance(sec["claims"], list)
        assert isinstance(sec["purpose"], str) and sec["purpose"]
    ls = data["lit_strategy"]
    assert {"queries", "must_contain"} <= set(ls)
    assert isinstance(ls["queries"], list) and ls["queries"]
    assert isinstance(ls["must_contain"], list) and ls["must_contain"]
    figs = data["viz_plan"]["figures"]
    assert isinstance(figs, list) and figs
    section_ids = {s["id"] for s in data["sections"]}
    for fig in figs:
        assert {"id", "source_section", "kind", "data_ref"} <= set(fig)
        assert fig["source_section"] in section_ids


def test_claims_ledger_template_rows():
    lines = [
        l
        for l in (ASSETS / "claims_ledger_template.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if l.strip()
    ]
    assert lines, "template must carry example rows"
    ids = set()
    for line in lines:
        row = json.loads(line)
        assert {"id", "claim", "origin", "evidence_level", "boundary"} <= set(row)
        # L4 (model memory) is not evidence and never enters the ledger.
        assert row["evidence_level"] in {"L0", "L1", "L2", "L3"}
        assert row["boundary"] == ledger_audit.LEVEL_BOUNDARY[row["evidence_level"]]
        assert row["origin"] == "field_common" or row["origin"].startswith(
            ("material:", "retrieval:")
        )
        assert row["id"] not in ids, "duplicate template id"
        ids.add(row["id"])
        if "conversions" in row:
            assert set(row["conversions"]) <= set(ledger_audit.CONVERSIONS)


def test_outline_schema_doc_references_canonical_and_extension():
    doc = (SKILL / "references" / "outline-schema.md").read_text(encoding="utf-8")
    # canonical references (paths, not copied definition tables)
    assert "paper-writer/references/evidence-discipline.md" in doc
    assert "paper-writer/references/verification-ladder.md" in doc
    assert "Rung" in doc
    # lit_strategy marked as our extension
    assert "lit_strategy" in doc
    assert "扩展" in doc
    # must NOT restate the canonical L0-L4 definition table wholesale
    assert "L1 full text / data" not in doc
    assert "L4 model memory" not in doc
    # module constants documented: hedge signal set + conversion whitelist
    for word in ("may", "could", "potentially", "likely"):
        assert word in doc
    for conv in ledger_audit.CONVERSIONS:
        assert conv in doc
    # marker convention and CLI documented
    assert "% @claim:" in doc
    assert "ledger_audit.py" in doc
    # harness-neutral payload
    assert "superpowers" not in doc.lower()