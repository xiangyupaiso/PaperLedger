"""End-to-end deterministic pipeline integration test (Stages 1 -> 7).

Exercises the complete PaperLedger script toolchain against the real CVPR 2025
template without requiring live network access, matplotlib, or a TeX compiler.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parent.parent
CVPR_TEMPLATE = REPO / "skills" / "paper-orchestrator" / "templates" / "cvpr2025"

import latex_compose  # noqa: E402
import ledger_audit  # noqa: E402
import lit_search  # noqa: E402
import plot_from_logs  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


def _mock_requests_factory():
    """Return a fake requests.get handling S2 calls across two stages."""
    call_log: list[str] = []

    def fake_get(url, params=None, headers=None, timeout=15):
        call_log.append(f"{url}::{params}")
        q = (params or {}).get("query", "")
        if "patch matching" in q:
            payload = {
                "data": [
                    {
                        "title": "Fast Patch Alignment via Local Descriptors",
                        "authors": [{"name": "Alice Smith"}, {"name": "Bob Lee"}],
                        "year": 2023,
                        "venue": "CVPR",
                        "externalIds": {"DOI": "10.1000/smith2023"},
                        "citationCount": 42,
                        "abstract": "We propose fast patch alignment for matching under viewpoint changes.",
                        "tldr": {"text": "Fast patch alignment summary."},
                        "url": "https://www.semanticscholar.org/paper/a",
                    },
                    {
                        "title": "Sparse Visual Keypoints Revisited",
                        "authors": [{"name": "Jane Doe"}],
                        "year": 2024,
                        "venue": "NeurIPS",
                        "externalIds": {},
                        "citationCount": 9,
                        "abstract": "",
                        "tldr": {"text": "Model-invented AI summary that L3 must drop."},
                        "url": "https://www.semanticscholar.org/paper/b",
                    },
                ]
            }
        elif "sparse alignment" in q:
            payload = {
                "data": [
                    {
                        "title": "Fast Patch Alignment via Local Descriptors",
                        "authors": [{"name": "Alice Smith"}, {"name": "Bob Lee"}],
                        "year": 2023,
                        "venue": "CVPR",
                        "externalIds": {"DOI": "10.1000/smith2023"},
                        "citationCount": 42,
                        "abstract": "We propose fast patch alignment for matching under viewpoint changes.",
                        "url": "https://www.semanticscholar.org/paper/a",
                    }
                ]
            }
        else:
            payload = {
                "data": [
                    {
                        "title": "Fast Descriptor Indexing in Vision",
                        "authors": [{"name": "Alice Smith"}],
                        "year": 2023,
                        "venue": "ICCV",
                        "externalIds": {"DOI": "10.1000/smith2023b"},
                        "citationCount": 5,
                        "abstract": "Descriptor indexing speeds up large-scale matching.",
                        "url": "https://www.semanticscholar.org/paper/c",
                    }
                ]
            }
        return SimpleNamespace(
            status_code=200,
            headers={},
            raise_for_status=lambda: None,
            json=lambda: payload,
            text=json.dumps(payload),
        )

    return fake_get, call_log


def _extract_strength_report(stdout: str) -> dict:
    marker = "STRENGTH MISMATCH REPORT (report-only, non-gating):\n"
    assert marker in stdout, stdout
    tail = stdout.split(marker, 1)[1]
    dec = json.JSONDecoder()
    obj, _ = dec.raw_decode(tail.lstrip())
    return obj


def test_full_pipeline_stage1_to_stage7(tmp_path: Path, monkeypatch, capsys):
    # ------------------------------------------------------------------ Stage 1-2
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "results.csv").write_text(
        "method,acc_top1,speedup_x,mem_gb\n"
        "Baseline,0.881,1.0,16\n"
        "ProtoMatch,0.934,1.8,12\n",
        encoding="utf-8",
    )
    (materials / "train_log.csv").write_text(
        "epoch,loss,acc\n"
        "1,0.850,0.724\n"
        "2,0.520,0.862\n"
        "3,0.310,0.934\n",
        encoding="utf-8",
    )

    claims_path = tmp_path / "claims.jsonl"
    base_claims = [
        {
            "id": "M1",
            "claim": "ProtoMatch achieves 93.4% accuracy with 1.8x speedup and 12GB memory.",
            "origin": "material:results.csv#L3",
            "evidence_level": "L1",
            "boundary": "any",
            "conversions": ["x100_percent"],
        },
        {
            "id": "M2",
            "claim": "Training converges to 0.31 loss and 0.93 rounded accuracy by epoch 3.",
            "origin": "material:train_log.csv#L2-L4",
            "evidence_level": "L1",
            "boundary": "any",
            "conversions": ["round_2dp"],
        },
        {
            "id": "F0",
            "claim": "Dense local features improve correspondence matching under viewpoint shifts.",
            "origin": "field_common",
            "evidence_level": "L0",
            "boundary": "directional",
        },
    ]
    _write_jsonl(claims_path, base_claims)

    outline_path = tmp_path / "outline.json"
    outline = {
        "title": "ProtoMatch: Grounded Patch Alignment",
        "venue": "CVPR 2025",
        "metadata": {
            "authors": [
                {
                    "name": "Ada Lovelace",
                    "affiliation": "Analytical Lab",
                    "email": "ada@example.edu",
                }
            ],
            "paper_id": "42",
        },
        "sections": [
            {"id": "intro", "kind": "introduction", "claims": ["F0", "M1"], "purpose": "Motivate problem."},
            {"id": "related", "kind": "related_work", "claims": [], "purpose": "Position prior work."},
            {"id": "method", "kind": "method", "claims": ["F0"], "purpose": "Describe framework."},
            {"id": "experiments", "kind": "experiments", "claims": ["M1", "M2"], "purpose": "Report metrics."},
            {"id": "conclusion", "kind": "conclusion", "claims": [], "purpose": "Wrap up."},
        ],
        "lit_strategy": {
            "queries": ["patch matching", "sparse alignment"],
            "must_contain": ["alignment"],
        },
        "viz_plan": {
            "figures": [
                {
                    "id": "tab_main",
                    "source_section": "experiments",
                    "kind": "table",
                    "data_ref": "materials/train_log.csv",
                }
            ]
        },
    }
    outline_path.write_text(json.dumps(outline, indent=2), encoding="utf-8")

    rc = ledger_audit.main([
        str(claims_path),
        "--materials",
        str(materials),
        "--outline",
        str(outline_path),
    ])
    capsys.readouterr()
    assert rc == 0

    # ------------------------------------------------------------------ Stage 3
    fake_get, _ = _mock_requests_factory()
    monkeypatch.setattr(lit_search.requests, "get", fake_get)

    papers_path = tmp_path / "papers.jsonl"
    bib_path = tmp_path / "refs.bib"
    lit_draft_path = tmp_path / "lit_claims.jsonl"
    nmap_path = tmp_path / "numeric_map.json"

    lit_search.main([
        "--queries-from", str(outline_path),
        "--limit", "5",
        "--fallback", "off",
        "--out", str(papers_path),
        "--bib", str(bib_path),
        "--emit-ledger-draft", str(lit_draft_path),
        "--emit-numeric-map", str(nmap_path),
        "--rank",
    ])
    capsys.readouterr()

    papers = [json.loads(l) for l in papers_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(papers) == 2  # duplicate S2 hit across two outline queries collapsed
    by_title = {p["title"]: p for p in papers}
    l2_key = by_title["Fast Patch Alignment via Local Descriptors"]["citekey"]
    l3_paper = by_title["Sparse Visual Keypoints Revisited"]
    l3_key = l3_paper["citekey"]
    assert l3_paper["tldr"] is None  # L3 AI summary suppressed by default

    nmap_initial = json.loads(nmap_path.read_text(encoding="utf-8"))
    assert set(nmap_initial.values()) == {l2_key, l3_key}

    # Incremental append with --existing-bib must never drift locked citekeys.
    lit_search.main([
        "--query", "fast descriptor indexing",
        "--limit", "3",
        "--fallback", "off",
        "--append",
        "--existing-bib", str(bib_path),
        "--out", str(papers_path),
        "--bib", str(bib_path),
        "--emit-ledger-draft", str(lit_draft_path),
        "--emit-numeric-map", str(nmap_path),
    ])
    capsys.readouterr()

    appended_papers = [json.loads(l) for l in papers_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(appended_papers) == 3
    appended_by_title = {p["title"]: p for p in appended_papers}
    assert appended_by_title["Fast Patch Alignment via Local Descriptors"]["citekey"] == l2_key
    assert appended_by_title["Sparse Visual Keypoints Revisited"]["citekey"] == l3_key
    extra_key = appended_by_title["Fast Descriptor Indexing in Vision"]["citekey"]
    assert extra_key not in {l2_key, l3_key}

    lit_rows = [json.loads(l) for l in lit_draft_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    _write_jsonl(claims_path, base_claims + lit_rows)
    numeric_map = json.loads(nmap_path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ Stage 4-5
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    (figures_dir / "fig_curve.pdf").write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
    (figures_dir / "fig_curve.png").write_bytes(b"\x89PNG\r\n\x1a\n")  # companion preview PNG

    tables_dir = tmp_path / "tables"
    tables_dir.mkdir()
    tab_tex = plot_from_logs.log_to_table(
        materials / "train_log.csv",
        {
            "columns": ["epoch", "loss", "acc"],
            "caption": "Training trajectory across epochs.",
            "label": "tab:main",
            "round": {"loss": 2, "acc": 2},
            "star": True,
            "headers": {"acc": "Top-1"},
            "bold_best": {"loss": "min", "acc": "max"},
        },
    )
    tab_tex = "% @claim: M2\n" + tab_tex
    (tables_dir / "tab_main.tex").write_text(tab_tex, encoding="utf-8")

    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    (sections_dir / "00_abstract.tex").write_text(
        "\\begin{abstract}\n"
        "% @claim: M1\n"
        "ProtoMatch reaches $93.4\\%$ accuracy at $1.8\\times$ speedup in 12GB memory.\n"
        "\\end{abstract}\n",
        encoding="utf-8",
    )
    (sections_dir / "01_intro.tex").write_text(
        "\\section{Introduction}\\label{sec:intro}\n"
        "In this section, we outline our core contributions.\n\n"
        "% @claim: F0\n"
        "Dense local features improve correspondence matching under viewpoint shifts "
        "(1) across scenes, (2) under occlusion, and (3) with compact descriptors.\n\n"
        "% @claim: M1\n"
        "Compared against ResNet-50 baselines, ProtoMatch attains $93.4\\%$ top-1 accuracy "
        "with $1.8\\times$ speedup inside 12GB.\n",
        encoding="utf-8",
    )
    (sections_dir / "02_related_work.tex").write_text(
        "\\section{Related Work}\\label{sec:related_work}\n"
        f"% @claim: R1\n"
        f"Smith et al.~(2023) studied patch alignment descriptors \\cite{{{l2_key}}}.\n\n"
        f"% @claim: R2\n"
        f"Doe \\cite{{{l3_key}}} addressed sparse visual keypoints.\n",
        encoding="utf-8",
    )
    approach_clean = (
        "\\section{Methodology}\\label{sec:method}\n"
        "Figure~\\ref{fig:curve} illustrates our progressive matching pipeline.\n\n"
        "\\begin{figure}[t]\n"
        "  \\centering\n"
        "  \\includegraphics[width=0.9\\linewidth]{figures/fig_curve}\n"
        "  % @claim: M2\n"
        "  \\caption{Optimization curve.}\n"
        "  \\label{fig:curve}\n"
        "\\end{figure}\n\n"
        "% @claim: F0\n"
        "Setting hyperparameter $\\alpha=.57$ keeps dense local matching stable across viewpoints.\n"
    )
    approach_path = sections_dir / "03_approach.tex"
    approach_path.write_text(approach_clean, encoding="utf-8")

    exp_weak_tex = (
        "\\section{Experiments}\\label{sec:experiments}\n"
        "Table~\\ref{tab:main} summarizes training progress across epochs.\n\n"
        "\\input{tables/tab_main}\n\n"
        "% @claim: M1\n"
        "Our method may improve top-1 accuracy to $93.4\\%$ with $1.8\\times$ faster inference.\n"
    )
    exp_path = sections_dir / "04_experiments.tex"
    exp_path.write_text(exp_weak_tex, encoding="utf-8")

    (sections_dir / "05_conclusion.tex").write_text(
        "\\section{Conclusion}\\label{sec:conclusion}\n"
        "% @claim: M1\n"
        "ProtoMatch achieves $93.4\\%$ accuracy within 12GB of GPU memory.\n\n"
        "Future work extends sparse patch matching to multi-camera video streams.\n",
        encoding="utf-8",
    )

    # Trap check: fabricated 99.9% and L3 citation outside related_work must fail gate.
    approach_path.write_text(
        approach_clean
        + f"\n% @claim: R2\nOur design achieves $99.9\\%$ precision per \\cite{{{l3_key}}}.\n",
        encoding="utf-8",
    )
    trap_rc = ledger_audit.main([
        str(claims_path),
        "--materials", str(materials),
        "--outline", str(outline_path),
        "--sections", str(sections_dir),
        "--tables", str(tables_dir),
        "--bib", str(bib_path),
    ])
    trap_out = capsys.readouterr()
    assert trap_rc == 1
    assert "99.9" in trap_out.out
    assert "R2" in trap_out.out and "related_work_only" in trap_out.out

    # Restore clean approach section and audit full draft + strength report.
    approach_path.write_text(approach_clean, encoding="utf-8")
    rc = ledger_audit.main([
        str(claims_path),
        "--materials", str(materials),
        "--outline", str(outline_path),
        "--sections", str(sections_dir),
        "--tables", str(tables_dir),
        "--bib", str(bib_path),
        "--strength-report",
    ])
    out = capsys.readouterr()
    assert rc == 0, out.out
    report = _extract_strength_report(out.out)
    assert len(report["weakened_strong"]) == 1
    assert report["weakened_strong"][0]["file"] == "04_experiments.tex"
    # Signposts, tabular rows, L0 directional sentence, and canonical L3 deixis are excluded;
    # the unbacked forward-step conclusion sentence is surfaced in overclaimed_weak.
    assert len(report["overclaimed_weak"]) == 1
    assert report["overclaimed_weak"][0]["file"] == "05_conclusion.tex"
    forward_fp = report["overclaimed_weak"][0]["fingerprint"]

    # ------------------------------------------------------------------ Stage 6
    out_dir = tmp_path / "compiled"
    compile_cmds: list[list[str]] = []

    def fake_which(name: str):
        return f"/usr/bin/{name}" if name == "pdflatex" else None

    def fake_run(cmd, cwd=None, capture_output=True, text=True, timeout=120, env=None):
        compile_cmds.append(list(cmd))
        cwd_p = Path(cwd)
        (cwd_p / "template.log").write_text("Output written on template.pdf (4 pages).\n", encoding="utf-8")
        (cwd_p / "template.blg").write_text("Database file #1: refs.bib\n", encoding="utf-8")
        (cwd_p / "template.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(latex_compose.shutil, "which", fake_which)
    monkeypatch.setattr(latex_compose.subprocess, "run", fake_run)

    compose_rep = latex_compose.compose(
        CVPR_TEMPLATE,
        sections_dir,
        bib_path,
        figures_dir,
        out_dir,
        numeric_map=numeric_map,
        tables_dir=tables_dir,
        outline_path=outline_path,
    )
    capsys.readouterr()
    assert compose_rep.ok is True
    assert compose_rep.compiled is True
    assert [c[0] for c in compile_cmds] == ["pdflatex", "bibtex", "pdflatex", "pdflatex"]

    wired_tex = (out_dir / "template.tex").read_text(encoding="utf-8")
    assert r"\bibliography{refs}" in wired_tex
    assert not (out_dir / "references.bib").exists()
    assert r"\title{ProtoMatch: Grounded Patch Alignment}" in wired_tex
    assert "Ada Lovelace" in wired_tex
    assert r"\def\paperID{42}" in wired_tex
    for ph in latex_compose.CVPR_PLACEHOLDERS:
        assert ph not in wired_tex

    assert (out_dir / "figures" / "fig_curve.pdf").is_file()
    assert not (out_dir / "figures" / "fig_curve.png").exists()
    composed_tab = (out_dir / "tables" / "tab_main.tex").read_text(encoding="utf-8")
    assert "@claim" not in composed_tab
    assert r"\textbf{0.31}" in composed_tab

    # Also verify compose protects \newcommand{\sys}[1]{#1} while bridging draft [1]
    macro_draft = "\\newcommand{\\sys}[1]{#1}\nPrior work studied descriptors [1].\n"
    bridged = latex_compose.to_cites(macro_draft, numeric_map)
    capsys.readouterr()
    assert "\\newcommand{\\sys}[1]{#1}" in bridged
    assert f"\\cite{{{numeric_map['1']}}}" in bridged

    # ------------------------------------------------------------------ Stage 7
    dispositions_path = tmp_path / "dispositions.json"
    dispositions_path.write_text(
        json.dumps(
            {
                "dispositions": [
                    {
                        "fingerprint": forward_fp,
                        "decision": "accept-as-future-scope",
                        "rationale": "Explicit future work sentence; makes no empirical claim.",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    exp_path.write_text(
        exp_weak_tex.replace(
            "Our method may improve top-1 accuracy to $93.4\\%$ with $1.8\\times$ faster inference.",
            "ProtoMatch achieves $93.4\\%$ top-1 accuracy with $1.8\\times$ faster inference.",
        ),
        encoding="utf-8",
    )

    rc7 = ledger_audit.main([
        str(claims_path),
        "--materials", str(materials),
        "--outline", str(outline_path),
        "--sections", str(sections_dir),
        "--tables", str(tables_dir),
        "--bib", str(bib_path),
        "--strength-report",
        "--dispositions", str(dispositions_path),
    ])
    out7 = capsys.readouterr()
    assert rc7 == 0, out7.out
    report7 = _extract_strength_report(out7.out)
    assert report7["weakened_strong"] == []
    assert report7["overclaimed_weak"] == []
    assert forward_fp in report7["disposed_fingerprints"]

    out_dir_a = tmp_path / "compiled_final_a"
    out_dir_b = tmp_path / "compiled_final_b"
    rep_a = latex_compose.compose(
        CVPR_TEMPLATE, sections_dir, bib_path, figures_dir, out_dir_a,
        numeric_map=numeric_map, tables_dir=tables_dir, outline_path=outline_path,
    )
    rep_b = latex_compose.compose(
        CVPR_TEMPLATE, sections_dir, bib_path, figures_dir, out_dir_b,
        numeric_map=numeric_map, tables_dir=tables_dir, outline_path=outline_path,
    )
    capsys.readouterr()
    assert rep_a.ok and rep_b.ok
    assert (out_dir_a / "template.tex").read_text(encoding="utf-8") == (
        out_dir_b / "template.tex"
    ).read_text(encoding="utf-8")
    assert (out_dir_a / "sections" / "04_experiments.tex").read_text(encoding="utf-8") == (
        out_dir_b / "sections" / "04_experiments.tex"
    ).read_text(encoding="utf-8")
    assert (out_dir_a / "tables" / "tab_main.tex").read_text(encoding="utf-8") == (
        out_dir_b / "tables" / "tab_main.tex"
    ).read_text(encoding="utf-8")
