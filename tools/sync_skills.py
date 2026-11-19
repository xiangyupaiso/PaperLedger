#!/usr/bin/env python3
"""Cross-platform skill mirror tool (stdlib-only replacement for sync-skills.ps1).

Mirrors only the skill directories explicitly listed in manifest.json from
manifest.source into each existing root in manifest.targets (plus
manifest.optional_targets only when --include-agents-root is passed).
Never touches any other directory in target roots and never silently creates
missing target roots.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class SyncError(RuntimeError):
    """Raised when manifest validation, safety guards, or sync verification fail."""


@dataclass
class SkillDiff:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    dirs_added: list[str] = field(default_factory=list)
    dirs_deleted: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.added or self.updated or self.deleted or self.dirs_added or self.dirs_deleted
        )


def expand_root_path(raw: str, *, base_dir: Path | None = None) -> Path:
    """Expand ~, env vars, and manifest/repo-relative paths without requiring existence."""
    if not isinstance(raw, str) or not raw.strip():
        raise SyncError(f"path entry must be a non-empty string, got {raw!r}")
    s = os.path.expanduser(os.path.expandvars(raw.strip()))
    p = Path(s)
    if p.is_absolute():
        return Path(os.path.abspath(str(p)))
    if base_dir is not None:
        cand_manifest = base_dir / p
        if cand_manifest.exists():
            return Path(os.path.abspath(str(cand_manifest)))
        if base_dir.name == "tools":
            cand_repo = base_dir.parent / p
            if cand_repo.exists():
                return Path(os.path.abspath(str(cand_repo)))
    return Path(os.path.abspath(str(Path.cwd() / p)))


def _is_link_or_reparse(path: Path) -> bool:
    """True for POSIX/Windows symlinks and Windows NTFS junctions/reparse points."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


def _validate_skill_name(name: str) -> str:
    if not isinstance(name, str) or not SKILL_NAME_RE.fullmatch(name):
        raise SyncError(
            f"unsafe or invalid skill name {name!r}; must match {SKILL_NAME_RE.pattern}"
        )
    return name


def read_manifest(manifest_path: Path) -> dict:
    """Load and structurally validate manifest JSON."""
    if not manifest_path.is_file():
        raise SyncError(
            f"manifest not found: {manifest_path} -- copy tools/manifest.example.json "
            "to tools/manifest.json or pass --manifest <path>"
        )
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SyncError(f"invalid manifest JSON {manifest_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SyncError(f"manifest root must be a JSON object: {manifest_path}")

    source = data.get("source")
    if not isinstance(source, str) or not source.strip():
        raise SyncError(f"manifest missing non-empty 'source': {manifest_path}")

    targets = data.get("targets")
    if not isinstance(targets, list) or not targets or not all(
        isinstance(t, str) and t.strip() for t in targets
    ):
        raise SyncError(f"manifest 'targets' must be a non-empty list of strings: {manifest_path}")

    opt = data.get("optional_targets", [])
    if opt is None:
        opt = []
    if not isinstance(opt, list) or not all(isinstance(t, str) and t.strip() for t in opt):
        raise SyncError(f"manifest 'optional_targets' must be a list of strings: {manifest_path}")

    raw_skills = data.get("skills")
    if not isinstance(raw_skills, list) or not raw_skills:
        raise SyncError(f"manifest 'skills' must be a non-empty list: {manifest_path}")

    skills: list[str] = []
    seen: set[str] = set()
    for item in raw_skills:
        if isinstance(item, dict):
            name = item.get("name")
        elif isinstance(item, str):
            name = item
        else:
            raise SyncError(f"manifest skill entry must be object or string, got {item!r}")
        _validate_skill_name(name)
        if name in seen:
            raise SyncError(f"duplicate skill in manifest: {name}")
        seen.add(name)
        skills.append(name)

    return {
        "source": source.strip(),
        "targets": [t.strip() for t in targets],
        "optional_targets": [t.strip() for t in opt],
        "skills": skills,
    }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _snapshot_tree(root: Path) -> tuple[dict[str, str], set[str]]:
    """Return ({rel_posix: sha256}, {rel_posix_dir}) while rejecting any link/reparse."""
    files: dict[str, str] = {}
    dirs: set[str] = set()
    if not root.exists():
        return files, dirs
    if _is_link_or_reparse(root):
        raise SyncError(f"refusing symlink/reparse directory: {root}")
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dp = Path(dirpath)
        rel_dir = dp.relative_to(root).as_posix()
        if rel_dir != ".":
            dirs.add(rel_dir)
        for d in dirnames:
            cand = dp / d
            if _is_link_or_reparse(cand):
                raise SyncError(f"refusing symlink/reparse directory inside tree: {cand}")
        for fn in filenames:
            cand = dp / fn
            if _is_link_or_reparse(cand):
                raise SyncError(f"refusing symlink/reparse file inside tree: {cand}")
            rel = cand.relative_to(root).as_posix()
            files[rel] = _sha256_file(cand)
    return files, dirs


def _compute_diff(
    src_files: dict[str, str],
    src_dirs: set[str],
    dst_files: dict[str, str],
    dst_dirs: set[str],
) -> SkillDiff:
    added = sorted(k for k in src_files if k not in dst_files)
    updated = sorted(k for k in src_files if k in dst_files and dst_files[k] != src_files[k])
    deleted = sorted(k for k in dst_files if k not in src_files)
    dirs_added = sorted(d for d in src_dirs if d not in dst_dirs)
    dirs_deleted = sorted((d for d in dst_dirs if d not in src_dirs), reverse=True)
    return SkillDiff(
        added=added,
        updated=updated,
        deleted=deleted,
        dirs_added=dirs_added,
        dirs_deleted=dirs_deleted,
    )


def _apply_mirror(src_skill: Path, dst_skill: Path, diff: SkillDiff) -> None:
    dst_skill.mkdir(parents=True, exist_ok=True)
    for d in diff.dirs_added:
        (dst_skill / d).mkdir(parents=True, exist_ok=True)
    for rel in diff.added + diff.updated:
        dst_file = dst_skill / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_skill / rel, dst_file)
    for rel in diff.deleted:
        (dst_skill / rel).unlink()
    for d in diff.dirs_deleted:
        dp = dst_skill / d
        if dp.is_dir():
            try:
                dp.rmdir()
            except OSError:
                pass


def sync_from_manifest(
    manifest_path: Path,
    *,
    dry_run: bool = False,
    include_agents_root: bool = False,
    stream=None,
) -> dict:
    """Validate manifest, mirror declared skills into existing targets, verify hashes."""
    out = stream or sys.stdout
    manifest_dir = manifest_path.resolve().parent
    manifest = read_manifest(manifest_path)

    src_root = expand_root_path(manifest["source"], base_dir=manifest_dir)
    if _is_link_or_reparse(src_root):
        raise SyncError(f"refusing symlink/reparse source root: {src_root}")
    if not src_root.is_dir():
        raise SyncError(f"source skill root missing: {src_root}")

    raw_targets = list(manifest["targets"])
    if include_agents_root:
        raw_targets.extend(manifest["optional_targets"])

    target_roots: list[Path] = []
    for raw_t in raw_targets:
        t_path = expand_root_path(raw_t, base_dir=manifest_dir)
        if _is_link_or_reparse(t_path):
            raise SyncError(f"refusing symlink/reparse target root: {t_path}")
        if not t_path.is_dir():
            raise SyncError(
                f"target root does not exist (refusing to create automatically): {t_path}"
            )
        target_roots.append(t_path)

    for skill in manifest["skills"]:
        src_skill = src_root / skill
        if _is_link_or_reparse(src_skill):
            raise SyncError(f"refusing symlink/reparse source skill dir: {src_skill}")
        if not src_skill.is_dir():
            raise SyncError(f"manifest skill missing under source: {src_skill}")

    summary = {"skills_synced": 0, "files_copied": 0, "files_deleted": 0, "targets": []}
    for t_root in target_roots:
        t_rec = {"root": str(t_root), "skills": {}}
        for skill in manifest["skills"]:
            src_skill = src_root / skill
            dst_skill = t_root / skill
            if dst_skill.exists() and _is_link_or_reparse(dst_skill):
                raise SyncError(f"refusing symlink/reparse target skill dir: {dst_skill}")
            if dst_skill.exists() and not dst_skill.is_dir():
                raise SyncError(f"target skill path exists as non-directory file: {dst_skill}")

            src_files, src_dirs = _snapshot_tree(src_skill)
            dst_files, dst_dirs = _snapshot_tree(dst_skill) if dst_skill.exists() else ({}, set())
            diff = _compute_diff(src_files, src_dirs, dst_files, dst_dirs)

            if not dry_run and diff.has_changes:
                _apply_mirror(src_skill, dst_skill, diff)
                verify_files, verify_dirs = _snapshot_tree(dst_skill)
                if verify_files != src_files or verify_dirs != src_dirs:
                    raise SyncError(
                        f"post-sync SHA-256 verification mismatch for {dst_skill}"
                    )

            copied = len(diff.added) + len(diff.updated)
            deleted = len(diff.deleted)
            summary["skills_synced"] += 1
            summary["files_copied"] += copied
            summary["files_deleted"] += deleted
            t_rec["skills"][skill] = {
                "added": len(diff.added),
                "updated": len(diff.updated),
                "deleted": deleted,
            }
            mode_tag = "[DRY-RUN] " if dry_run else ""
            if diff.has_changes:
                print(
                    f"{mode_tag}sync {skill} -> {dst_skill}: "
                    f"+{len(diff.added)} ~{len(diff.updated)} -{deleted}",
                    file=out,
                )
            else:
                print(f"{mode_tag}sync {skill} -> {dst_skill}: up-to-date", file=out)
        summary["targets"].append(t_rec)
    return summary


def run_self_test() -> None:
    """Execute self-contained verification inside an isolated temporary directory."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "src_skills"
        t1 = root / "target_one"
        opt_missing = root / "missing_agents_root"
        src.mkdir()
        t1.mkdir()

        # Populate two skills + one unrelated neighbor in target_one
        (src / "skill-a").mkdir()
        (src / "skill-a" / "SKILL.md").write_text("# A\n", encoding="utf-8")
        (src / "skill-a" / "sub").mkdir()
        (src / "skill-a" / "sub" / "data.txt").write_text("v1", encoding="utf-8")

        (t1 / "skill-a").mkdir()
        (t1 / "skill-a" / "stale.txt").write_text("stale", encoding="utf-8")
        (t1 / "keep-other").mkdir()
        (t1 / "keep-other" / "note.txt").write_text("keep", encoding="utf-8")

        manifest = root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "source": str(src),
                    "targets": [str(t1)],
                    "optional_targets": [str(opt_missing)],
                    "skills": [{"name": "skill-a", "category": "general"}],
                }
            ),
            encoding="utf-8",
        )

        with open(os.devnull, "w", encoding="utf-8") as sink:
            # 1) Dry run makes zero writes
            dry = sync_from_manifest(manifest, dry_run=True, stream=sink)
            assert dry["files_copied"] == 2 and dry["files_deleted"] == 1
            assert (t1 / "skill-a" / "stale.txt").is_file()
            assert not (t1 / "skill-a" / "SKILL.md").exists()

            # 2) Real sync mirrors strictly & ignores missing optional_targets by default
            rep = sync_from_manifest(manifest, dry_run=False, stream=sink)
            assert rep["files_copied"] == 2 and rep["files_deleted"] == 1
            assert not (t1 / "skill-a" / "stale.txt").exists()
            assert (t1 / "skill-a" / "sub" / "data.txt").read_text(encoding="utf-8") == "v1"
            assert (t1 / "keep-other" / "note.txt").read_text(encoding="utf-8") == "keep"
            assert not opt_missing.exists()

            # 3) Idempotent second run
            rep2 = sync_from_manifest(manifest, dry_run=False, stream=sink)
            assert rep2["files_copied"] == 0 and rep2["files_deleted"] == 0

            # 4) --include-agents-root fails on missing optional root without creating it
            try:
                sync_from_manifest(manifest, include_agents_root=True, stream=sink)
            except SyncError:
                assert not opt_missing.exists()
            else:
                raise AssertionError("expected SyncError on missing optional root")

            # 5) Unsafe skill name rejected
            bad_manifest = root / "bad_manifest.json"
            bad_manifest.write_text(
                json.dumps(
                    {
                        "source": str(src),
                        "targets": [str(t1)],
                        "skills": [{"name": "../escape", "category": "general"}],
                    }
                ),
                encoding="utf-8",
            )
            try:
                read_manifest(bad_manifest)
            except SyncError:
                pass
            else:
                raise AssertionError("expected SyncError for traversal skill name")

            # 6) Link/reparse check (best-effort OS symlink when permitted)
            link_target = root / "outside"
            link_target.mkdir()
            link_path = t1 / "skill-link"
            try:
                os.symlink(link_target, link_path, target_is_directory=True)
            except OSError:
                pass
            else:
                assert _is_link_or_reparse(link_path)

    print("sync_skills.py self-test OK")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mirror manifest-listed skills across local agent skill directories."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parent / "manifest.json",
        help="Path to manifest.json (default: tools/manifest.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned additions/updates/deletions without modifying files",
    )
    parser.add_argument(
        "--include-agents-root",
        action="store_true",
        help="Also sync optional_targets (missing roots still fail instead of being created)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run built-in isolated temporary-directory self-test and exit",
    )
    args = parser.parse_args(argv)

    try:
        if args.self_test:
            run_self_test()
            return 0
        sync_from_manifest(
            args.manifest,
            dry_run=args.dry_run,
            include_agents_root=args.include_agents_root,
        )
        return 0
    except SyncError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
