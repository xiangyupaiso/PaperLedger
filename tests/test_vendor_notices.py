"""Provenance/divergence notices for the vendored PaperOrchestra upstream.

The notices file is the provenance record every later porting task cites
(brief Task 2). It must carry the exact vendor commit hash on its first
line so later tasks pin the same upstream revision.
"""
import re
from pathlib import Path

NOTICES_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "paper-orchestrator"
    / "references"
    / "vendor-notices.md"
)


def test_vendor_notices_file_exists():
    assert NOTICES_PATH.is_file(), f"missing {NOTICES_PATH}"


def test_vendor_notices_required_strings():
    text = NOTICES_PATH.read_text(encoding="utf-8")
    # 1) upstream license spelled out
    assert "Apache-2.0" in text
    # 2) first line is `VENDOR_COMMIT: <40-hex>` (validated by regex)
    first_line = text.splitlines()[0].strip()
    assert re.fullmatch(r"VENDOR_COMMIT: [0-9a-f]{40}", first_line), first_line
    # 3) divergence section present
    assert "分歧记录" in text
    # 4) cvpr2025 author-kit retention section present
    assert "作者套件" in text
    # 5) outline-schema extension field recorded
    assert "lit_strategy" in text


def test_notices_reflect_ported_state_and_timeout_deviation():
    """Fix-wave F8: the 'no upstream .py ported yet' claim is stale once
    lit_search.py / latex_compose.py carry ported code; the timeout and
    limit-parameterization deviations must be mirrored into 分歧记录."""
    text = NOTICES_PATH.read_text(encoding="utf-8")
    assert "尚未搬入任何上游" not in text, "stale pre-port claim must be gone"
    assert "lit_search.py" in text and "latex_compose.py" in text
    assert "5s→10s" in text, "timeout deviation mirrored into notices"
    assert "参数化" in text, "limit parameterization deviation recorded"
