"""Tests for tools/sync_skills.py (cross-platform stdlib skill mirror)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import sync_skills  # noqa: E402


def _make_manifest(
    path: Path,
    *,
    source: str,
    targets: list[str],
    optional_targets: list[str] | None = None,
    skills: list[str] | None = None,
) -> Path:
    payload = {
        "source": source,
        "targets": targets,
        "optional_targets": optional_targets or [],
        "skills": [
            {"name": s, "category": "general"}
            for s in (skills if skills is not None else ["paper-orchestrator"])
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _populate_fixture(tmp_path: Path):
    src = tmp_path / "src"
    t1 = tmp_path / "t1"
    opt = tmp_path / "agents"
    src.mkdir()
    t1.mkdir()
    opt.mkdir()

    (src / "paper-orchestrator" / "references").mkdir(parents=True)
    (src / "paper-orchestrator" / "SKILL.md").write_text("# v2\n", encoding="utf-8")
    (src / "paper-orchestrator" / "references" / "rules.md").write_text("rules\n", encoding="utf-8")

    # Pre-existing target content + stale file + unrelated sibling skill
    (t1 / "paper-orchestrator" / "old_dir").mkdir(parents=True)
    (t1 / "paper-orchestrator" / "SKILL.md").write_text("# v1\n", encoding="utf-8")
    (t1 / "paper-orchestrator" / "old_dir" / "stale.txt").write_text("drop\n", encoding="utf-8")
    (t1 / "unrelated-skill").mkdir()
    (t1 / "unrelated-skill" / "keep.txt").write_text("untouched\n", encoding="utf-8")

    manifest = _make_manifest(
        tmp_path / "manifest.json",
        source=str(src),
        targets=[str(t1)],
        optional_targets=[str(opt)],
    )
    return src, t1, opt, manifest


def test_dry_run_sync_and_idempotency(tmp_path: Path, capsys):
    src, t1, opt, manifest = _populate_fixture(tmp_path)

    # Dry-run reports changes without modifying target
    assert sync_skills.main(["--manifest", str(manifest), "--dry-run"]) == 0
    out_dry = capsys.readouterr().out
    assert "[DRY-RUN]" in out_dry
    assert (t1 / "paper-orchestrator" / "SKILL.md").read_text(encoding="utf-8") == "# v1\n"
    assert (t1 / "paper-orchestrator" / "old_dir" / "stale.txt").is_file()
    assert not (opt / "paper-orchestrator").exists()

    # Real sync mirrors strictly within listed skill dir & preserves sibling
    assert sync_skills.main(["--manifest", str(manifest)]) == 0
    out_sync = capsys.readouterr().out
    assert "+1 ~1 -1" in out_sync
    assert (t1 / "paper-orchestrator" / "SKILL.md").read_text(encoding="utf-8") == "# v2\n"
    assert (t1 / "paper-orchestrator" / "references" / "rules.md").is_file()
    assert not (t1 / "paper-orchestrator" / "old_dir").exists()
    assert (t1 / "unrelated-skill" / "keep.txt").read_text(encoding="utf-8") == "untouched\n"
    assert not (opt / "paper-orchestrator").exists()

    # Second run is idempotent
    assert sync_skills.main(["--manifest", str(manifest)]) == 0
    assert "up-to-date" in capsys.readouterr().out


def test_include_agents_root_opt_in_and_missing_root_refusal(tmp_path: Path, capsys):
    src, t1, opt, manifest = _populate_fixture(tmp_path)

    assert sync_skills.main(["--manifest", str(manifest), "--include-agents-root"]) == 0
    capsys.readouterr()
    assert (opt / "paper-orchestrator" / "SKILL.md").read_text(encoding="utf-8") == "# v2\n"

    # Missing optional target fails loudly when opted in and never creates directory
    missing_opt = tmp_path / "never_created_agents"
    manifest2 = _make_manifest(
        tmp_path / "manifest2.json",
        source=str(src),
        targets=[str(t1)],
        optional_targets=[str(missing_opt)],
    )
    assert sync_skills.main(["--manifest", str(manifest2), "--include-agents-root"]) == 1
    assert "does not exist" in capsys.readouterr().err
    assert not missing_opt.exists()


def test_missing_source_missing_target_and_invalid_skill_names(tmp_path: Path, capsys):
    src = tmp_path / "src"
    t1 = tmp_path / "t1"
    src.mkdir()
    (src / "good").mkdir()
    (src / "good" / "SKILL.md").write_text("ok", encoding="utf-8")

    # Missing target root fails without creating t1
    m_missing_t = _make_manifest(tmp_path / "m1.json", source=str(src), targets=[str(t1)], skills=["good"])
    assert sync_skills.main(["--manifest", str(m_missing_t)]) == 1
    assert not t1.exists()
    capsys.readouterr()

    # Missing source root fails
    t1.mkdir()
    m_missing_s = _make_manifest(tmp_path / "m2.json", source=str(tmp_path / "nope"), targets=[str(t1)], skills=["good"])
    assert sync_skills.main(["--manifest", str(m_missing_s)]) == 1
    capsys.readouterr()

    for bad in ("../escape", ".hidden", "sub/dir", ""):
        m_bad = _make_manifest(tmp_path / "m_bad.json", source=str(src), targets=[str(t1)], skills=[bad])
        assert sync_skills.main(["--manifest", str(m_bad)]) == 1
        assert "unsafe" in capsys.readouterr().err.lower()


def test_mocked_link_or_reparse_refusal(tmp_path: Path, monkeypatch, capsys):
    src, t1, _opt, manifest = _populate_fixture(tmp_path)
    dst_skill = t1 / "paper-orchestrator"

    for poisoned in (src / "paper-orchestrator", t1, dst_skill, dst_skill / "SKILL.md"):
        monkeypatch.setattr(
            sync_skills,
            "_is_link_or_reparse",
            lambda p, target=poisoned: Path(p) == target,
        )
        rc = sync_skills.main(["--manifest", str(manifest)])
        err = capsys.readouterr().err
        assert rc == 1
        assert "symlink/reparse" in err
        # Original file untouched on refusal
        assert (dst_skill / "SKILL.md").read_text(encoding="utf-8") == "# v1\n"


def test_relative_repo_skills_source_resolution(tmp_path: Path, capsys):
    # Mirror repository manifest pattern: tools/manifest.example.json uses "./skills"
    t_claude = tmp_path / "claude"
    t_codex = tmp_path / "codex"
    t_gemini = tmp_path / "gemini"
    for d in (t_claude, t_codex, t_gemini):
        d.mkdir()

    example = json.loads((TOOLS_DIR / "manifest.example.json").read_text(encoding="utf-8"))
    example["source"] = "./skills"
    example["targets"] = [str(t_claude), str(t_codex), str(t_gemini)]
    example["optional_targets"] = []

    # Place copy under tmp_tools/ so base_dir.name == "tools" check is skipped unless CWD=REPO;
    # run with explicit dry-run from REPO or verify expand_root_path on real tools/manifest.example.json.
    resolved = sync_skills.expand_root_path("./skills", base_dir=TOOLS_DIR)
    assert resolved == (REPO / "skills").resolve()

    local_manifest = tmp_path / "manifest.json"
    local_manifest.write_text(json.dumps(example), encoding="utf-8")
    # Running from REPO resolves "./skills" to REPO / "skills"
    assert sync_skills.main(["--manifest", str(local_manifest), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "paper-orchestrator" in out and "academic-humanizer" in out


def test_cli_self_test(capsys):
    assert sync_skills.main(["--self-test"]) == 0
    assert "self-test OK" in capsys.readouterr().out
