"""Task 8 gate: tools/sync-skills.ps1 keeps manifest skills byte-identical
across harness skill roots and never touches anything outside the manifest.

The heavy scenario (fake temp roots, fake manifest, default vs
-IncludeAgentsRoot runs, -DryRun zero-write checks, non-manifest survival,
idempotent re-run, failure exit codes) lives inside the script's -SelfTest
mode so it exercises the real PowerShell code path. This wrapper only
asserts the contract: exit 0 and "SELFTEST PASS" on stdout.

Stdlib-only by design (no repo imports, no conftest dependency).
"""
import json
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "sync-skills.ps1"
# Public package: the shipped example manifest (the script itself takes any
# path via -ManifestPath; its built-in -SelfTest uses a fake manifest).
MANIFEST = REPO_ROOT / "tools" / "manifest.example.json"

WRITING = {
    "academic-humanizer", "benchmark-paper-template", "intro-drafter",
    "paper-polish", "paper-writer", "pre-submission-reviewer",
    "tech-paper-template",
}
RESEARCH_TOOL = {"deep-research", "figure-designer"}
GENERAL = {"paper-orchestrator"}
# The categories sync-skills.ps1's Read-Manifest accepts. Keep in lockstep.
ALLOWED_CATEGORIES = {"writing", "research-tool", "general"}


def test_sync_script_selftest():
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        import pytest
        pytest.skip("pwsh 7 not on PATH")
    proc = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(SCRIPT), "-SelfTest"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    assert proc.returncode == 0, (
        f"SelfTest exited {proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert "SELFTEST PASS" in proc.stdout, (
        f"no SELFTEST PASS marker\n--- stdout ---\n{proc.stdout}"
    )


def test_manifest_contract():
    assert MANIFEST.is_file(), f"missing {MANIFEST}"
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert m["source"] == "~/.claude/skills"
    assert m["targets"] == ["~/.codex/skills", "~/.gemini/config/skills"]
    assert m["optional_targets"] == ["~/.agents/skills"]
    # The opt-in flag must be explained next to the optional root.
    assert "-IncludeAgentsRoot" in m["_comment_optional_targets"]
    skills = m["skills"]
    assert len(skills) == 10
    by_cat = {}
    for entry in skills:
        assert set(entry) == {"name", "category"}
        by_cat.setdefault(entry["category"], set()).add(entry["name"])
    assert by_cat == {
        "writing": WRITING,
        "research-tool": RESEARCH_TOOL,
        "general": GENERAL,
    }


def test_manifest_categories_match_script_allowlist():
    """Anti-drift: every shipped manifest category must be accepted by
    sync-skills.ps1's Read-Manifest allowlist (writing|research-tool|general).
    The example manifest is the documented quickstart path, so a category the
    script rejects would make the quickstart die with MANIFEST REJECTED."""
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for entry in m["skills"]:
        assert entry["category"] in ALLOWED_CATEGORIES, (
            f"manifest category {entry['category']!r} for {entry['name']!r} "
            f"is not in the sync-skills.ps1 allowlist "
            f"{sorted(ALLOWED_CATEGORIES)}"
        )