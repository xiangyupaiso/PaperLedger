"""Task 5: latex_compose -- staging, wiring, numeric-cite bridge, integrity.

Anchors for the real-template test come from the Task 2 structure memo
(skill/paper-orchestrator/references/vendor-notices.md, section 四):
entry file template.tex (no main.tex upstream), unique \\maketitle at :27,
example body :29-:63 replaced (region :28-:64), bibliography block :65-:69
kept, commented appendix :71-:75 kept, \\end{document} :77.
"""
import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import latex_compose
from latex_compose import CiteError, compose, to_cites

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
# Public layout: the vendor clone is not shipped. The author-kit files are
# pinned by SHA-256 instead (recorded from the VENDOR_COMMIT clone).
CVPR_HASHES = FIXTURES / "cvpr2025_sha256.json"
INSTALLED_CVPR = REPO / "skills" / "paper-orchestrator" / "templates" / "cvpr2025"

BIB = r"""@inproceedings{alpha2024deep,
  title = {{Deep Things}},
  author = {A, Author and B, Writer},
  booktitle = {Proc. Conf},
  year = {2024},
}
@article{beta2023wide,
  title = {{Wide Things}},
  author = {C, Person},
  journal = {J. Stuff},
  year = {2023},
}
"""

# Placeholder strings named verbatim in the vendor-notices structure memo.
CVPR_PLACEHOLDERS = [
    "Abstract here.",
    "Introduction here.",
    "Related work here.",
    "Methodology here.",
    "Experimental setup, results, and analysis here.",
    "Conclusion here.",
]


@pytest.fixture
def no_tex(monkeypatch):
    """Deterministic 'no LaTeX toolchain' regardless of the host machine."""
    monkeypatch.setattr(latex_compose.shutil, "which", lambda name: None)


def _project(tmp_path, template, sections, bib_name="refs.bib", figures=None):
    """Materialize sections/bib/figures inputs; return compose() kwargs."""
    sec_dir = tmp_path / "sections"
    sec_dir.mkdir()
    for name, text in sections.items():
        (sec_dir / name).write_text(text, encoding="utf-8")
    bib = tmp_path / bib_name
    bib.write_text(BIB, encoding="utf-8")
    fig_dir = None
    if figures is not None:
        fig_dir = tmp_path / "figsrc"
        fig_dir.mkdir()
        for name, data in figures.items():
            (fig_dir / name).write_bytes(data)
    return dict(
        template_dir=FIXTURES / template,
        sections_dir=sec_dir,
        bib_path=bib,
        figures_dir=fig_dir,
        out_dir=tmp_path / "manuscript",
    )


def test_wires_inputs_in_order(tmp_path, no_tex):
    kw = _project(
        tmp_path,
        "mini_template",
        {
            "03_results.tex": "Results body.\n",
            "01_intro.tex": "Intro body.\n",
            "02_method.tex": "Method body.\n",
        },
    )
    report = compose(**kw)
    out = kw["out_dir"]
    tex = (out / "main.tex").read_text(encoding="utf-8")
    inputs = [
        r"\input{sections/01_intro}",
        r"\input{sections/02_method}",
        r"\input{sections/03_results}",
    ]
    positions = [tex.index(s) for s in inputs]  # raises if absent
    assert positions == sorted(positions), "inputs must follow filename order"
    marker = "% >>> paper-orchestrator: sections"
    assert tex.index(marker) < positions[0], "inputs go below the marker"
    for name in ("01_intro", "02_method", "03_results"):
        assert (out / "sections" / f"{name}.tex").is_file()
    assert report.ok is True
    assert report.compiled is None
    assert report.missing_citations == []
    assert report.missing_files == []
    assert report.raster_refs == []


def test_real_cvpr_template_wiring(tmp_path, no_tex):
    kw = _project(
        tmp_path,
        "cvpr_real",
        {
            "01_intro.tex": "\\section{Introduction}\nReal intro.\n",
            "02_method.tex": "\\section{Method}\nReal method.\n",
        },
        bib_name="references.bib",
    )
    report = compose(**kw)
    tex = (kw["out_dir"] / "template.tex").read_text(encoding="utf-8")
    # \input wiring sits after the unique \maketitle (memo :27).
    first_input = tex.index(r"\input{sections/01_intro}")
    assert tex.index(r"\maketitle") < first_input
    assert first_input < tex.index(r"\input{sections/02_method}")
    # Example body (memo :29-:63) is gone, placeholders and paired fences.
    for placeholder in CVPR_PLACEHOLDERS:
        assert placeholder not in tex
    assert "%%%%%%%%% ABSTRACT" not in tex
    assert "%%%%%%%%% CONCLUSION" not in tex
    # Bibliography block (memo :65-:69) and commented appendix (:71-:75) kept.
    assert r"\bibliographystyle{ieeenat_fullname}" in tex
    assert r"\bibliography{references}" in tex
    assert tex.index(r"\bibliography{references}") > first_input
    assert "% \\appendix" in tex
    assert r"\end{document}" in tex
    # Preamble copied from the template dir, so \input{preamble} resolves.
    assert (kw["out_dir"] / "preamble.tex").is_file()
    assert report.missing_files == []
    assert report.ok is True


def test_to_cites_converts_and_errors(tmp_path, no_tex):
    numeric_map = {"1": "alpha2024deep", "2": "beta2023wide"}
    assert to_cites("See [1,2].", numeric_map) == (
        "See \\cite{alpha2024deep,beta2023wide}."
    )
    assert to_cites("Solo [1].", numeric_map) == "Solo \\cite{alpha2024deep}."
    # Non-numeric bracket groups are left alone (optional args etc.).
    assert to_cites(r"\includegraphics[width=3cm]{f}", numeric_map) == (
        r"\includegraphics[width=3cm]{f}"
    )
    # Missing number / out-of-range number -> CiteError.
    with pytest.raises(CiteError):
        to_cites("Bad [3].", numeric_map)
    with pytest.raises(CiteError):
        to_cites("Bad [0].", numeric_map)
    # R1: several numbers -> SAME citekey is legal, dedup, never an error.
    dup_map = {"1": "alpha2024deep", "2": "alpha2024deep"}
    assert to_cites("Both [1,2].", dup_map) == "Both \\cite{alpha2024deep}."
    # ...and compose surfaces it as a warning only.
    kw = _project(
        tmp_path, "mini_template", {"01_intro.tex": "Both [1,2].\n"}
    )
    report = compose(**kw, numeric_map=dup_map)
    assert report.ok is True
    assert any("alpha2024deep" in w for w in report.warnings)
    body = (kw["out_dir"] / "sections" / "01_intro.tex").read_text(
        encoding="utf-8"
    )
    assert body == "Both \\cite{alpha2024deep}.\n"


def test_raster_figure_flagged(tmp_path, no_tex):
    kw = _project(
        tmp_path,
        "mini_template",
        {
            "01_intro.tex": (
                "\\includegraphics[width=\\linewidth]{figures/x.png}\n"
                "\\includegraphics{figures/y.pdf}\n"
                "\\includegraphics{figures/absent.pdf}\n"
            )
        },
        figures={
            "x.png": b"\x89PNG\r\n\x1a\nstub",
            "y.pdf": b"%PDF-1.4 stub",
        },
    )
    report = compose(**kw)
    assert report.raster_refs == ["figures/x.png"]
    assert report.ok is False
    assert report.missing_files == ["figures/absent.pdf"]
    assert (kw["out_dir"] / "figures" / "x.png").is_file()


def test_missing_citation_detected(tmp_path, no_tex):
    kw = _project(
        tmp_path,
        "mini_template",
        {
            "01_intro.tex": (
                "\\citep[see][]{ghost2020missing} "
                "\\citet{alpha2024deep} "
                "\\cite{beta2023wide,other2021gone}\n"
            )
        },
    )
    report = compose(**kw)
    assert sorted(report.missing_citations) == [
        "ghost2020missing",
        "other2021gone",
    ]
    assert report.ok is False


def test_no_toolchain_compiled_none_ok_true(tmp_path, monkeypatch):
    empty = tmp_path / "empty_bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))  # PATH stubbed clear of any TeX
    kw = _project(tmp_path, "mini_template", {"01_intro.tex": "Clean body.\n"})
    report = compose(**kw)
    assert report.compiled is None
    assert report.ok is True
    assert any("toolchain" in w.lower() for w in report.warnings)


def test_compose_strips_claim_markers(tmp_path, no_tex):
    draft = (
        "% @claim:c1\n"
        "Our method improves accuracy.\n"
        "\n"
        "   % @claim:c2\n"
        "Another claim sentence.\n"
        "A trailing comment stays. % keep me\n"
    )
    kw = _project(tmp_path, "mini_template", {"01_intro.tex": draft})
    compose(**kw)
    body = (kw["out_dir"] / "sections" / "01_intro.tex").read_text(
        encoding="utf-8"
    )
    assert "@claim" not in body
    assert "Our method improves accuracy.\n" in body
    assert "Another claim sentence.\n" in body
    assert "A trailing comment stays. % keep me\n" in body
    entry = (kw["out_dir"] / "main.tex").read_text(encoding="utf-8")
    assert "@claim" not in entry


def test_cvpr_template_copied_byte_identical():
    # The hash fixture ships in the public package; a missing fixture must fail
    # loudly instead of silently dropping the byte-identity gate.
    assert CVPR_HASHES.is_file(), f"missing byte-identity fixture: {CVPR_HASHES}"
    expected = json.loads(CVPR_HASHES.read_text(encoding="utf-8"))
    expected.pop("_source", None)
    expected.pop("_note", None)
    assert INSTALLED_CVPR.is_dir()
    assert {p.name for p in INSTALLED_CVPR.iterdir()} == set(expected)
    for name, digest in sorted(expected.items()):
        actual = hashlib.sha256((INSTALLED_CVPR / name).read_bytes()).hexdigest()
        assert actual == digest, f"{name} differs from the VENDOR_COMMIT author-kit"


def _fake_run_factory(calls, produce_pdf):
    def fake_run(command, **kwargs):
        calls.append((list(command), kwargs))
        exe = Path(command[0]).name.lower()
        if produce_pdf and exe in ("pdflatex", "xelatex", "latexmk"):
            stem = Path(command[-1]).stem
            (Path(kwargs["cwd"]) / f"{stem}.pdf").write_bytes(b"%PDF-1.4 stub")
        return SimpleNamespace(returncode=0 if produce_pdf else 1,
                               stdout="", stderr="")
    return fake_run


def test_compile_sequence_stubbed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        latex_compose.shutil, "which",
        lambda name: f"/fake/{name}" if name in ("pdflatex", "bibtex") else None,
    )
    monkeypatch.setenv("TEXINPUTS", "/polluted")
    calls = []
    monkeypatch.setattr(
        latex_compose.subprocess, "run", _fake_run_factory(calls, True)
    )
    kw = _project(tmp_path, "mini_template", {"01_intro.tex": "Body.\n"})
    report = compose(**kw)
    assert report.compiled is True
    assert report.ok is True
    exes = [Path(c[0][0]).name for c in calls]
    assert exes == ["pdflatex", "bibtex", "pdflatex", "pdflatex"]
    for _, kwargs in calls:
        assert "TEXINPUTS" not in kwargs["env"]  # upstream env scrub kept
        assert kwargs["cwd"] == str(kw["out_dir"]) or Path(
            kwargs["cwd"]
        ) == kw["out_dir"]
    assert (kw["out_dir"] / "main.pdf").is_file()


def test_latexmk_preferred_when_available(tmp_path, monkeypatch):
    monkeypatch.setattr(
        latex_compose.shutil, "which", lambda name: f"/fake/{name}"
    )
    calls = []
    monkeypatch.setattr(
        latex_compose.subprocess, "run", _fake_run_factory(calls, True)
    )
    kw = _project(tmp_path, "mini_template", {"01_intro.tex": "Body.\n"})
    report = compose(**kw)
    assert report.compiled is True
    assert len(calls) == 1
    assert Path(calls[0][0][0]).name == "latexmk"


def test_compile_failure_sets_ok_false(tmp_path, monkeypatch):
    monkeypatch.setattr(
        latex_compose.shutil, "which",
        lambda name: f"/fake/{name}" if name in ("pdflatex", "bibtex") else None,
    )
    calls = []
    monkeypatch.setattr(
        latex_compose.subprocess, "run", _fake_run_factory(calls, False)
    )
    kw = _project(tmp_path, "mini_template", {"01_intro.tex": "Body.\n"})
    report = compose(**kw)
    assert report.compiled is False
    assert report.ok is False
    assert report.warnings


def test_no_marker_no_bibliography_keeps_end_document(tmp_path, no_tex):
    tpl = tmp_path / "tpl"
    tpl.mkdir()
    (tpl / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\maketitle\n"
        "Example body.\n\\end{document}\n",
        encoding="utf-8",
    )
    kw = _project(tmp_path, "mini_template", {"01_intro.tex": "Body.\n"})
    kw["template_dir"] = tpl
    compose(**kw)
    tex = (kw["out_dir"] / "main.tex").read_text(encoding="utf-8")
    assert r"\end{document}" in tex
    assert tex.index(r"\maketitle") < tex.index(r"\input{sections/01_intro}")


def test_cite_error_message_tolerates_nonnumeric_map_keys():
    with pytest.raises(CiteError):
        to_cites("[9]", {"x": "k"})

# ------------------------------------------------- final-review fix-wave (F2/F4)


def test_to_cites_skips_math_spans():
    """F2: bare [digit] groups inside math are indexing, not citations."""
    numeric_map = {"1": "alpha2024deep", "2": "beta2023wide"}
    for tex in (
        "$x[1]$ stays.",
        r"\(y[1]\) stays.",
        r"\[z[1,2]\] stays.",
        "$$a[2]$$ stays.",
    ):
        assert to_cites(tex, numeric_map) == tex, tex
    # mixed: prose [1] bridged, math [1] untouched in the same document
    assert to_cites("See [1]; index $x[1]$.", numeric_map) == (
        r"See \cite{alpha2024deep}; index $x[1]$."
    )


def test_to_cites_skips_cite_optional_args():
    r"""F2 probe: \cite[1]{key} must NOT become \cite\cite{mapped}{key}."""
    numeric_map = {"1": "alpha2024deep", "2": "beta2023wide"}
    for tex in (
        r"\cite[1]{key}",
        r"\citep[2]{key}",
        r"\citet[1,2]{key}",
        r"\cite*[1][2]{key}",
        r"\citep[see][p.~12]{key}",
    ):
        assert to_cites(tex, numeric_map) == tex, tex


def test_to_cites_prose_still_bridged_and_warns(capsys):
    """F2: prose [1]/[1,2] still bridge; each conversion emits a stderr note."""
    numeric_map = {"1": "alpha2024deep", "2": "beta2023wide"}
    capsys.readouterr()
    out = to_cites("First [1] then [1,2].", numeric_map)
    assert out == (
        r"First \cite{alpha2024deep} then \cite{alpha2024deep,beta2023wide}."
    )
    err = capsys.readouterr().err
    assert "[1]" in err and "alpha2024deep" in err
    assert "[1,2]" in err and "beta2023wide" in err
    assert err.count("\n") == 2, "one warning line per conversion"
    # no conversion -> no warning
    to_cites("Nothing here $x[1]$.", numeric_map)
    assert capsys.readouterr().err == ""


def test_compose_placeholder_survival_warns(tmp_path, no_tex):
    """F4: cvpr2025 title/author/paperID placeholders surviving compose -> warning."""
    kw = _project(
        tmp_path, "cvpr_real", {"01_intro.tex": "Real intro.\n"},
        bib_name="references.bib",
    )
    report = compose(**kw)
    assert report.ok is True, "placeholder warning must be non-failing"
    joined = "\n".join(report.warnings)
    assert "placeholder" in joined.lower()
    assert "My Title" in joined
    assert "paperID" in joined or "12345678" in joined
    assert "outline.json" in joined


def test_compose_placeholder_replaced_no_warning(tmp_path, no_tex):
    """F4: replaced title/author/paperID -> no placeholder warning."""
    tpl = tmp_path / "tpl"
    shutil.copytree(FIXTURES / "cvpr_real", tpl)
    entry = tpl / "template.tex"
    text = entry.read_text(encoding="utf-8")
    text = text.replace(r"\title{My Title}", r"\title{A Real Title}")
    text = text.replace("Ambitious AI Researcher", "Real Author")
    text = text.replace(r"\def\paperID{12345678}", r"\def\paperID{42}")
    entry.write_text(text, encoding="utf-8")
    kw = _project(
        tmp_path, "cvpr_real", {"01_intro.tex": "Real intro.\n"},
        bib_name="references.bib",
    )
    kw["template_dir"] = tpl
    report = compose(**kw)
    assert report.ok is True
    assert not any("placeholder" in w.lower() for w in report.warnings)


# ------------------------------------------------- Phase 0 regression tests


def test_cvpr_bib_auto_synced_and_stale_bib_removed(tmp_path, no_tex):
    kw = _project(
        tmp_path,
        "cvpr_real",
        {"01_intro.tex": "Real intro \\cite{alpha2024deep}.\n"},
        bib_name="refs.bib",
    )
    report = compose(**kw)
    out = kw["out_dir"]
    tex = (out / "template.tex").read_text(encoding="utf-8")
    assert r"\bibliography{refs}" in tex
    assert r"\bibliography{references}" not in tex
    assert (out / "refs.bib").is_file()
    assert not (out / "references.bib").exists()
    assert report.missing_citations == []
    assert report.ok is True


def test_compile_checks_log_and_blg_even_if_pdf_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(
        latex_compose.shutil,
        "which",
        lambda name: f"/fake/{name}" if name in ("pdflatex", "bibtex") else None,
    )

    def fake_bad_log(command, **kwargs):
        cwd = Path(kwargs["cwd"])
        exe = Path(command[0]).name.lower()
        if exe == "pdflatex":
            stem = Path(command[-1]).stem
            (cwd / f"{stem}.pdf").write_bytes(b"%PDF-1.4 broken")
            (cwd / f"{stem}.log").write_text(
                "! Undefined control sequence.\n"
                "LaTeX Warning: Citation `missing2024' on page 1 undefined.\n"
                "LaTeX Warning: There were undefined citations.\n",
                encoding="utf-8",
            )
        elif exe == "bibtex":
            (cwd / f"{command[1]}.blg").write_text(
                "Warning--I didn't find a database entry for \"missing2024\"\n",
                encoding="utf-8",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(latex_compose.subprocess, "run", fake_bad_log)
    kw = _project(tmp_path, "mini_template", {"01_intro.tex": "Body.\n"})
    report = compose(**kw)
    assert report.compiled is False
    assert report.ok is False
    assert any("compile" in w.lower() for w in report.warnings)


def test_tables_dir_staged_stripped_and_checked(tmp_path, no_tex):
    kw = _project(
        tmp_path,
        "mini_template",
        {"01_intro.tex": "See \\input{tables/tab_main}.\n"},
    )
    tab_dir = tmp_path / "tables"
    tab_dir.mkdir()
    (tab_dir / "tab_main.tex").write_text(
        "% @claim:E1\n"
        "\\begin{table}[t]\n"
        "Main table [1] and \\cite{ghost_tab_key}.\n"
        "\\end{table}\n",
        encoding="utf-8",
    )
    report = compose(
        **kw,
        tables_dir=tab_dir,
        numeric_map={"1": "alpha2024deep"},
    )
    staged_tab = (kw["out_dir"] / "tables" / "tab_main.tex").read_text(encoding="utf-8")
    assert "@claim" not in staged_tab
    assert r"\cite{alpha2024deep}" in staged_tab
    assert report.missing_files == []
    assert report.missing_citations == ["ghost_tab_key"]
    assert report.ok is False


def test_outline_metadata_injected_and_idempotent(tmp_path, no_tex):
    outline = tmp_path / "outline.json"
    outline.write_text(
        json.dumps({
            "title": "Deterministic Provenance for Research Papers",
            "venue": "CVPR 2025",
            "metadata": {
                "authors": [
                    {
                        "name": "Alice Smith",
                        "affiliation": "Example Lab",
                        "email": "alice_s@example.edu",
                    },
                    {
                        "name": "Bob Jones",
                        "affiliation": "Test University",
                        "email": "bob@test.edu",
                    },
                ],
                "paper_id": "4291",
            },
            "sections": [],
            "lit_strategy": {"queries": ["q"], "must_contain": ["m"]},
            "viz_plan": {"figures": []},
        }),
        encoding="utf-8",
    )
    kw = _project(
        tmp_path,
        "cvpr_real",
        {"01_intro.tex": "Draft v1.\n"},
        bib_name="refs.bib",
    )
    report1 = compose(**kw, outline_path=outline)
    assert report1.ok is True
    assert not any("placeholder" in w.lower() for w in report1.warnings)
    tex1 = (kw["out_dir"] / "template.tex").read_text(encoding="utf-8")
    assert r"\title{Deterministic Provenance for Research Papers}" in tex1
    assert "Alice Smith" in tex1 and "Bob Jones" in tex1
    assert r"alice\_s@example.edu" in tex1
    assert r"\def\paperID{4291}" in tex1
    # Stage 7 edits sections/ and re-runs compose: metadata stays intact.
    (kw["sections_dir"] / "01_intro.tex").write_text("Polished v2.\n", encoding="utf-8")
    report2 = compose(**kw, outline_path=outline)
    assert report2.ok is True
    assert not any("placeholder" in w.lower() for w in report2.warnings)
    tex2 = (kw["out_dir"] / "template.tex").read_text(encoding="utf-8")
    assert r"\title{Deterministic Provenance for Research Papers}" in tex2
    assert (kw["out_dir"] / "sections" / "01_intro.tex").read_text(encoding="utf-8") == "Polished v2.\n"


def test_companion_preview_png_excluded_when_pdf_exists(tmp_path, no_tex):
    kw = _project(
        tmp_path,
        "mini_template",
        {"01_intro.tex": "\\includegraphics{figures/conv.pdf}\n"},
        figures={
            "conv.pdf": b"%PDF-1.4 vector",
            "conv.png": b"\x89PNG\r\n\x1a\npreview",
            "standalone.png": b"\x89PNG\r\n\x1a\nstandalone",
        },
    )
    report = compose(**kw)
    assert report.ok is True
    assert (kw["out_dir"] / "figures" / "conv.pdf").is_file()
    assert not (kw["out_dir"] / "figures" / "conv.png").exists()
    assert (kw["out_dir"] / "figures" / "standalone.png").is_file()


def test_wire_handles_stray_brace_and_pre_maketitle_abstract(tmp_path, no_tex):
    tpl = tmp_path / "tpl_iclr"
    tpl.mkdir()
    (tpl / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\begin{abstract}\n"
        "Template dummy abstract.\n"
        "\\end{abstract}\n"
        "\\maketitle\n"
        "Example intro.\n"
        "{\n"
        "Stray group in example.\n"
        "}\n"
        "\\bibliographystyle{plain}\n"
        "\\bibliography{refs}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    kw = _project(
        tmp_path,
        "mini_template",
        {"00_abstract.tex": "\\begin{abstract}\nReal abstract.\n\\end{abstract}\n"},
    )
    kw["template_dir"] = tpl
    report = compose(**kw)
    assert report.ok is True
    tex = (kw["out_dir"] / "main.tex").read_text(encoding="utf-8")
    assert "Template dummy abstract." not in tex
    assert "Stray group in example." not in tex
    assert r"\input{sections/00_abstract}" in tex


def test_to_cites_protects_macros_equations_comments_and_expands_ranges():
    nmap = {"1": "k1", "2": "k2", "3": "k3"}
    tex = (
        "\\newcommand{\\foo}[1]{#1}\n"
        "% [1] commented out\n"
        "\\begin{equation}\n"
        "x[1] = 0\n"
        "\\end{equation}\n"
        "Prior works [1-3] and [1--2] agree.\n"
    )
    out = to_cites(tex, nmap)
    assert r"\newcommand{\foo}[1]{#1}" in out
    assert "% [1] commented out" in out
    assert "x[1] = 0" in out
    assert r"\cite{k1,k2,k3}" in out
    assert r"\cite{k1,k2}" in out
    with pytest.raises(CiteError):
        to_cites("Bad range [3-1].", nmap)


def test_integrity_ignores_comments_and_checks_natbib_variants(tmp_path, no_tex):
    kw = _project(
        tmp_path,
        "mini_template",
        {
            "01_intro.tex": (
                "% \\input{sections/ghost}\n"
                "% \\includegraphics{figures/ghost.png}\n"
                "% \\cite{ghost_comment_key}\n"
                "As shown by \\citeauthor{alpha2024deep} and \\citealp{missing_alp}.\n"
            )
        },
    )
    report = compose(**kw)
    assert report.missing_files == []
    assert report.raster_refs == []
    assert report.missing_citations == ["missing_alp"]
    assert report.ok is False
