"""Task 6: ledger_audit -- graded claims ledger, numeric provenance audit,
strength-mismatch report (report-only, no numeric budget/quota anywhere).

Binding convention (controller decision): sections/*.tex carry
``% @claim:<id>[,<id>...]`` comment lines above claim sentences; a numeric
sentence with NO marker is an orphan violation, a marker pointing at a
nonexistent id is a dead-link violation. Level->boundary mapping is derived
(L1 any / L2 headline_only / L3 related_work_only / L0 directional / L4 none).
"""
import json
import subprocess
import sys
from pathlib import Path

import ledger_audit
from ledger_audit import (
    audit_claims,
    audit_numbers,
    audit_strength_mismatch,
    load_claims,
)

SCRIPT = Path(ledger_audit.__file__).resolve()

E1 = {
    "id": "E1",
    "claim": "Our model reaches 0.93 accuracy.",
    "origin": "material:results.csv#L2-L3",
    "evidence_level": "L1",
    "boundary": "any",
}
E3 = {
    "id": "E3",
    "claim": "Smith et al. (2023) addressed graph classification.",
    "origin": "retrieval:smith2023",
    "evidence_level": "L3",
    "boundary": "related_work_only",
}


def _materials(tmp_path):
    m = tmp_path / "materials"
    m.mkdir()
    (m / "results.csv").write_text(
        "epoch,acc\n1,0.93\n2,0.95\n", encoding="utf-8"
    )  # 3 lines
    (m / "metrics.csv").write_text("acc,0.9345\n", encoding="utf-8")  # 1 line
    return m


def _sections(tmp_path, files):
    sec = tmp_path / "sections"
    sec.mkdir(exist_ok=True)
    for name, text in files.items():
        (sec / name).write_text(text, encoding="utf-8")
    return sec


def _ledger(tmp_path, rows):
    p = tmp_path / "claims.jsonl"
    p.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------- audit_claims


def test_audit_dead_line_range_and_boundary_mismatch(tmp_path):
    m = _materials(tmp_path)  # results.csv has only 3 lines
    rows = [
        {  # #L10-L15 beyond file length -> dead line ref
            "id": "D1",
            "claim": "x",
            "origin": "material:results.csv#L10-L15",
            "evidence_level": "L1",
            "boundary": "any",
        },
        {  # L3 + directional contradicts derived boundary related_work_only
            "id": "B1",
            "claim": "y",
            "origin": "retrieval:smith2023",
            "evidence_level": "L3",
            "boundary": "directional",
        },
        {  # missing evidence_level
            "id": "M1",
            "claim": "z",
            "origin": "material:results.csv#L1-L2",
            "boundary": "any",
        },
    ]
    v = audit_claims(_ledger(tmp_path, rows), m)
    assert len(v) == 3
    dead = next(x for x in v if "D1" in x)
    assert "L10-L15" in dead or "L10" in dead
    contra = next(x for x in v if "B1" in x)
    assert "L3" in contra and "directional" in contra
    missing = next(x for x in v if "M1" in x)
    assert "evidence_level" in missing


def test_audit_claims_L4_field_common_and_bad_origin(tmp_path):
    m = _materials(tmp_path)
    rows = [
        {  # L4 supports nothing; never enters the ledger
            "id": "Z1",
            "claim": "a remembered fact",
            "origin": "retrieval:x",
            "evidence_level": "L4",
            "boundary": "none",
        },
        {  # field_common with digits + camelCase identifier
            "id": "F1",
            "claim": "ImageNet has 1000 classes.",
            "origin": "field_common",
            "evidence_level": "L0",
            "boundary": "directional",
        },
        {  # field_common with capitalized multi-word name
            "id": "F2",
            "claim": "The Smith Group proposed this.",
            "origin": "field_common",
            "evidence_level": "L0",
            "boundary": "directional",
        },
        {  # clean field_common: no digits, no proper-noun-like tokens
            "id": "F3",
            "claim": "Neural networks are widely used.",
            "origin": "field_common",
            "evidence_level": "L0",
            "boundary": "directional",
        },
        {  # origin file does not exist -> dead link
            "id": "G1",
            "claim": "w",
            "origin": "material:nope.csv#L1",
            "evidence_level": "L1",
            "boundary": "any",
        },
        {  # undeclared conversion name
            "id": "C1",
            "claim": "v",
            "origin": "material:results.csv#L2",
            "evidence_level": "L1",
            "boundary": "any",
            "conversions": ["bogus_conv"],
        },
    ]
    v = audit_claims(_ledger(tmp_path, rows), m)
    assert len(v) == 5
    for cid in ("Z1", "F1", "F2", "G1", "C1"):
        assert any(cid in x for x in v), cid
    assert not any("F3" in x for x in v), "clean field_common must pass"


# --------------------------------------------------------------- audit_numbers


def test_audit_numbers_found_and_orphan(tmp_path):
    m = _materials(tmp_path)
    sec = _sections(
        tmp_path,
        {
            "03_results.tex": (
                "\\section{Results}\n"
                "% @claim:E1\n"
                "Our model reaches 0.93 accuracy.\n"
                "The fabricated score is 42.7 on the benchmark.\n"
            )
        },
    )
    v = audit_numbers(sec, [E1], m)
    assert len(v) == 1
    assert "42.7" in v[0]
    assert "03_results.tex:4" in v[0], "violation must carry the line number"
    assert "orphan" in v[0].lower(), "second sentence is unmarked -> orphan"
    assert "0.93" not in v[0], "0.93 is in the origin span and must pass"


def test_audit_numbers_ignores_cites_math_counters(tmp_path):
    m = _materials(tmp_path)
    tex = (
        "\\section{Introduction}\n"
        "Following \\cite{smith2023}, we use the setup of \\citet{jones2021}\n"
        "and \\citep[see][p.~12]{lee2020}.\n"
        "As shown in \\ref{fig:2} and \\eqref{eq:3}, labels \\label{sec:1}.\n"
        "The learning rate is $1e^{-3}$ and the bound is $0.5$.\n"
        "\\begin{equation}\n"
        "a = 42.7 + 99.9\n"
        "\\end{equation}\n"
        "\\begin{align*}\n"
        "x &= 12.34 \\\\\n"
        "y &= 56.78\n"
        "\\end{align*}\n"
        "\\begin{gather}\n"
        "z = 77.7\n"
        "\\end{gather}\n"
        "\\setcounter{page}{1}\n"
        "\\addtocounter{figure}{2}\n"
        "\\newcounter{mycount}\n"
        "\\stepcounter{mycount}\n"
        "\\arabic{mycount}\n"
        "\\value{page}\n"
        "\\thepage\n"
        "% @claim:E1\n"
        "Our model reaches 0.93 accuracy.\n"
    )
    sec = _sections(tmp_path, {"01_intro.tex": tex})
    v = audit_numbers(sec, [E1], m)
    assert v == [], f"excluded numbers must not be scanned: {v}"


def test_claim_marker_binding(tmp_path):
    m = _materials(tmp_path)
    sec = _sections(
        tmp_path,
        {
            "03_results.tex": (
                "\\section{Results}\n"
                "% @claim:E1\n"
                "Our model reaches 0.93 accuracy.\n"
            ),
            "04_extra.tex": (
                "\\section{Extra}\n" "The score is 42.7.\n"
            ),
            "05_dead.tex": (
                "\\section{Dead}\n"
                "% @claim:NOPE\n"
                "Our model reaches 0.93 accuracy.\n"
            ),
        },
    )
    v = audit_numbers(sec, [E1], m)
    assert len(v) == 2
    orphan = next(x for x in v if "orphan" in x.lower())
    assert "04_extra.tex" in orphan and "42.7" in orphan
    dead = next(x for x in v if "dead" in x.lower())
    assert "05_dead.tex" in dead and "NOPE" in dead
    assert not any("03_results.tex" in x for x in v), "marked alignment passes"


def test_audit_L3_in_methods_flagged(tmp_path):
    m = _materials(tmp_path)
    sec = _sections(
        tmp_path,
        {
            "01_related.tex": (
                "\\section{Related Work}\n"
                "% @claim:E3\n"
                "Smith et al. (2023) addressed graph classification.\n"
            ),
            "02_method.tex": (
                "\\section{Method}\n"
                "% @claim:E3\n"
                "We follow the pipeline of \\cite{smith2023} with three stages.\n"
            ),
        },
    )
    v = audit_numbers(sec, [E3], m)
    assert len(v) == 1
    assert "02_method.tex" in v[0]
    assert "E3" in v[0]
    assert "smith2023" in v[0], "violation must locate the citekey"
    assert "method" in v[0].lower()
    assert not any("01_related.tex" in x for x in v)


def test_conversion_whitelist_declared_only(tmp_path):
    m = _materials(tmp_path)
    e1p = {**E1, "id": "E1P", "conversions": ["x100_percent"]}
    e1r = {
        **E1,
        "id": "E1R",
        "origin": "material:metrics.csv#L1",
        "conversions": ["round_2dp"],
    }
    sec = _sections(
        tmp_path,
        {
            "a.tex": "% @claim:E1P\nOur model reaches 93% accuracy.\n",
            "b.tex": "% @claim:E1\nOur model reaches 93% accuracy.\n",
            "c.tex": "% @claim:E1R\nOur model reaches 0.93 accuracy.\n",
            "d.tex": "% @claim:E1\nOur model reaches 0.93 accuracy.\n",
        },
    )
    v = audit_numbers(sec, [E1, e1p, e1r], m)
    assert len(v) == 1, f"only the undeclared conversion must fail: {v}"
    assert "b.tex" in v[0] and "93" in v[0]


def test_audit_numbers_level_and_retrieval_limits(tmp_path):
    m = _materials(tmp_path)
    e2 = {
        "id": "E2",
        "claim": "The method improves accuracy.",
        "origin": "retrieval:jones2021",
        "evidence_level": "L2",
        "boundary": "headline_only",
    }
    # L2 (abstract) cannot support a specific number, even bound.
    sec = _sections(
        tmp_path, {"03_results.tex": "% @claim:E2\nThe score is 0.93.\n"}
    )
    v = audit_numbers(sec, [e2], m)
    assert len(v) == 1
    assert "E2" in v[0] and "0.93" in v[0] and "L2" in v[0]


# ------------------------------------------------------ audit_strength_mismatch


def test_strength_report_no_numeric_budget(tmp_path):
    m = _materials(tmp_path)
    sec = _sections(
        tmp_path,
        {
            "03_results.tex": (
                "\\section{Results}\n"
                "% @claim:E1\n"
                "Our model may reach 0.93 accuracy.\n"
            ),
            "01_related.tex": (
                "\\section{Related Work}\n"
                "% @claim:E3\n"
                "Smith et al. (2023) achieved strong results with a "
                "three-stage pipeline.\n"
            ),
        },
    )
    report = audit_strength_mismatch(sec, [E1, E3])
    assert set(report) == {"weakened_strong", "overclaimed_weak"}
    assert len(report["weakened_strong"]) == 1
    assert len(report["overclaimed_weak"]) == 1
    w = report["weakened_strong"][0]
    o = report["overclaimed_weak"][0]
    assert "E1" in w["claim_ids"]
    assert "may" in w["hedge_words"]
    assert "E3" in o["claim_ids"]
    # fuzzy claim<->sentence alignment via difflib is reported
    assert 0.0 <= w["match_ratio"] <= 1.0
    assert w["matched_claim"] == "E1"
    # per-item disposition advice offers BOTH directions, never forced
    for item in (w, o):
        assert "upgrade-to-assertive" in item["advice"]
        assert "fix-ledger" in item["advice"] and "shrink-claim" in item["advice"]
    # NO numeric budget / quota / gate fields anywhere in the output
    blob = json.dumps(report).lower()
    assert "budget" not in blob and "quota" not in blob
    banned_keys = {"budget", "quota", "count", "threshold", "limit", "max_words"}
    for item in report["weakened_strong"] + report["overclaimed_weak"]:
        assert not (banned_keys & set(item))
    # hedging vocabulary is EXACTLY the four-word signal set;
    # limitations/suggest/indicate are not penalty words in any constant
    assert set(ledger_audit.HEDGE_WORDS) == {"may", "could", "potentially", "likely"}
    for name, val in vars(ledger_audit).items():
        if not name.isupper():
            continue
        if isinstance(val, str):
            texts = [val]
        elif isinstance(val, (tuple, list, set, frozenset)):
            texts = [x for x in val if isinstance(x, str)]
        elif isinstance(val, dict):
            texts = [x for x in val if isinstance(x, str)] + [
                x for x in val.values() if isinstance(x, str)
            ]
        else:
            continue
        for t in texts:
            for banned in ("limitations", "suggest", "indicate"):
                assert banned not in t.lower(), (name, t)


def test_strength_unbound_and_non_penalty_words(tmp_path):
    sec = _sections(
        tmp_path,
        {
            "04_discussion.tex": (
                "\\section{Discussion}\n"
                "% @claim:E1\n"
                "These results suggest that the method indicates gains, "
                "with limitations.\n"
                "The score is 0.93.\n"
            )
        },
    )
    report = audit_strength_mismatch(sec, [E1])
    # suggest/indicate/limitations are NOT hedging signals -> no weakened hit
    assert report["weakened_strong"] == []
    # the unbound categorical sentence is reported (report-only)
    assert len(report["overclaimed_weak"]) == 1
    o = report["overclaimed_weak"][0]
    assert o["claim_ids"] == []
    assert "04_discussion.tex" in o["file"]


# ------------------------------------------------------------------------ CLI


def test_cli_exit_codes_and_strength_non_gating(tmp_path):
    m = _materials(tmp_path)
    ledger = _ledger(tmp_path, [E1, E3])
    sec = _sections(
        tmp_path,
        {
            "03_results.tex": (
                "\\section{Results}\n"
                "% @claim:E1\n"
                "Our model may reach 0.93 accuracy.\n"
            ),
            "01_related.tex": (
                "\\section{Related Work}\n"
                "% @claim:E3\n"
                "Smith et al. (2023) addressed graph classification.\n"
            ),
        },
    )
    base = [sys.executable, str(SCRIPT), str(ledger), "--materials", str(m)]
    r = subprocess.run(
        base + ["--sections", str(sec)], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr
    # strength report prints but does NOT gate the exit code
    r = subprocess.run(
        base + ["--sections", str(sec), "--strength-report"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "weakened_strong" in r.stdout and "overclaimed_weak" in r.stdout
    assert "budget" not in r.stdout.lower()
    # an orphan numeric sentence gates exit 1
    (sec / "04_extra.tex").write_text(
        "\\section{Extra}\nThe score is 42.7.\n", encoding="utf-8"
    )
    r = subprocess.run(
        base + ["--sections", str(sec)], capture_output=True, text=True
    )
    assert r.returncode == 1
    assert "42.7" in r.stdout
    # claims-only mode (no --sections) still audits the ledger
    bad = _ledger(tmp_path, [{**E1, "boundary": "directional"}])
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(bad), "--materials", str(m)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1


def test_load_claims_roundtrip(tmp_path):
    p = _ledger(tmp_path, [E1, E3])
    rows = load_claims(p)
    assert [r["id"] for r in rows] == ["E1", "E3"]


# ------------------------------------------------- Round 1 review regressions


def test_audit_numbers_sign_flip_flagged(tmp_path):
    """IMPORTANT 1: a direction-flipped value must NOT pass the gate."""
    m = tmp_path / "materials"
    m.mkdir()
    (m / "r.csv").write_text("delta,0.5\n", encoding="utf-8")
    (m / "s.csv").write_text("delta,-0.5\n", encoding="utf-8")
    e1 = {
        "id": "E1",
        "claim": "The change is 0.5.",
        "origin": "material:r.csv#L1",
        "evidence_level": "L1",
        "boundary": "any",
    }
    e1n = {**e1, "id": "E1N", "origin": "material:s.csv#L1"}
    sec = _sections(
        tmp_path,
        {
            "a.tex": "% @claim:E1\nThe change is -0.5.\n",  # sign flip -> violate
            "b.tex": "% @claim:E1\nThe change is 0.5.\n",  # agrees -> pass
            "c.tex": "% @claim:E1N\nThe change is -0.5.\n",  # agrees -> pass
            "d.tex": "% @claim:E1\nThe change is +0.5.\n",  # +0.5 == 0.5 -> pass
        },
    )
    v = audit_numbers(sec, [e1, e1n], m)
    assert len(v) == 1, f"only the sign-flip must fail: {v}"
    assert "a.tex" in v[0] and "-0.5" in v[0]


def test_audit_numbers_comment_dollar_not_swallow(tmp_path):
    """IMPORTANT 2: a comment's $ must not pair with prose math and swallow it."""
    m = _materials(tmp_path)
    sec = _sections(
        tmp_path,
        {"x.tex": "% note $5\nThe score is 42.7 and we use $x$ here.\n"},
    )
    v = audit_numbers(sec, [E1], m)
    assert any("42.7" in x for x in v), f"42.7 must still be audited: {v}"


def test_audit_numbers_escaped_dollars_consistent(tmp_path):
    """IMPORTANT 2: escaped \\$ are literal text, not math delimiters."""
    m = _materials(tmp_path)
    sec = _sections(tmp_path, {"y.tex": "Costs are \\$100 and \\$200.\n"})
    v = audit_numbers(sec, [E1], m)
    # both literal-dollar numbers are scanned (orphan); neither silently blanked
    assert any("100" in x and "200" in x for x in v), f"both must surface: {v}"


def test_dangling_dead_marker_flagged(tmp_path):
    """IMPORTANT 3: marker->nonexistent id is a dead-link UNCONDITIONALLY."""
    m = _materials(tmp_path)
    sec = _sections(
        tmp_path,
        {
            "x.tex": "Prose sentence.\n% @claim:GHOST\n",  # marker at EOF
            "y.tex": "% @claim:GHOST2\n\\section{Method}\n",  # only structural after
        },
    )
    v = audit_numbers(sec, [E1], m)
    assert len(v) == 2, f"both dangling dead markers must flag: {v}"
    assert any("GHOST" in x for x in v)
    assert any("GHOST2" in x for x in v)

# ------------------------------------------------- final-review fix-wave (F1/F3/F9/F11)


def test_cli_sections_missing_dir_fail_closed(tmp_path):
    """F1 merge blocker: --sections pointing at a nonexistent dir must NOT
    silently report '0 violations' (Path.glob on a missing dir yields nothing)."""
    m = _materials(tmp_path)
    ledger = _ledger(tmp_path, [E1])
    missing = tmp_path / "no_such_sections"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(ledger), "--materials", str(m),
         "--sections", str(missing)],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, f"fail-open on missing sections dir: {r.stdout}"
    assert "0 violation(s)" not in r.stdout
    assert r.stderr.strip(), "must emit an actionable stderr error"
    assert "no_such_sections" in r.stderr


def test_cli_sections_empty_dir_fail_closed(tmp_path):
    """F1: an existing dir with no .tex files is equally fail-closed."""
    m = _materials(tmp_path)
    ledger = _ledger(tmp_path, [E1])
    empty = tmp_path / "empty_sections"
    empty.mkdir()
    base = [sys.executable, str(SCRIPT), str(ledger), "--materials", str(m),
            "--sections", str(empty)]
    r = subprocess.run(base, capture_output=True, text=True)
    assert r.returncode != 0
    assert "0 violation(s)" not in r.stdout
    assert "empty_sections" in r.stderr
    # a dir holding only non-.tex files is still 'no .tex files'
    (empty / "notes.txt").write_text("not a section\n", encoding="utf-8")
    r = subprocess.run(base, capture_output=True, text=True)
    assert r.returncode != 0
    assert ".tex" in r.stderr


def test_cli_missing_claims_file_clean_error(tmp_path):
    """F11: missing claims file -> clean actionable stderr + exit 1, no traceback."""
    m = _materials(tmp_path)
    missing = tmp_path / "absent_claims.jsonl"
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(missing), "--materials", str(m)],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
    assert "Traceback" not in r.stderr
    assert "absent_claims.jsonl" in r.stderr
    assert r.stderr.strip()


def test_leading_decimal_prose_number_audited(tmp_path):
    """F3: '.57' in prose is a data number (was escaping NUMBER_RE entirely)."""
    m = _materials(tmp_path)
    sec = _sections(
        tmp_path,
        {
            "a.tex": "% @claim:E1\nThe rate is .57.\n",  # not in span -> violate
            "b.tex": "% @claim:E1\nWe set $\alpha=.57$ and reach 0.93 accuracy.\n",
            "c.tex": "% @claim:E1\nThe drop is -.5.\n",  # sign captured -> violate
            "d.tex": "Unmarked .05 significance.\n",  # orphan -> violate
        },
    )
    v = audit_numbers(sec, [E1], m)
    assert len(v) == 3, f"expected a/c/d violations only: {v}"
    assert any("a.tex" in x and ".57" in x for x in v)
    assert any("c.tex" in x and "-.5" in x for x in v), "sign must be captured"
    assert any("d.tex" in x and ".05" in x for x in v)
    assert not any("b.tex" in x for x in v), "$.57$ in math stays excluded"


def test_canonical_l3_deixis_not_flagged(tmp_path):
    r"""F9: 'X et al. (Year) addressed Y \cite{...}' bound to L3 in related
    work is exactly what L3 semantics supports -> NOT overclaimed_weak."""
    sec = _sections(
        tmp_path,
        {
            "01_related.tex": (
                r"\section{Related Work}" "\n"
                "% @claim:E3\n"
                "Smith et al. (2023) addressed graph classification "
                r"\cite{smith2023}." "\n"
            )
        },
    )
    report = audit_strength_mismatch(sec, [E3])
    assert report["overclaimed_weak"] == []
    assert report["weakened_strong"] == []


def test_deixis_exemption_is_narrow(tmp_path):
    """F9: real overclaims stay flagged even with L3 binding."""
    sec = _sections(
        tmp_path,
        {
            "01_related.tex": (
                r"\section{Related Work}" "\n"
                "% @claim:E3\n"
                # deixis shape BUT a performance number -> still flagged
                "Smith et al. (2023) studied graph classification and reached "
                r"0.95 accuracy \cite{smith2023}." "\n"
            ),
            "02_other.tex": (
                r"\section{Discussion}" "\n"
                "% @claim:E3\n"
                # categorical assertion, no deixis shape -> still flagged
                r"Graph classification is solved \cite{smith2023}." "\n"
            ),
            "03_method.tex": (
                r"\section{Method}" "\n"
                "% @claim:E3\n"
                # canonical shape but in a methods section -> still flagged
                "Smith et al. (2023) addressed graph classification "
                r"\cite{smith2023}." "\n"
            ),
            "04_unbound.tex": (
                r"\section{Intro}" "\n"
                # canonical shape but unbound -> still flagged
                "Smith et al. (2023) addressed graph classification "
                r"\cite{smith2023}." "\n"
            ),
        },
    )
    report = audit_strength_mismatch(sec, [E3])
    files = {o["file"] for o in report["overclaimed_weak"]}
    assert files == {"01_related.tex", "02_other.tex", "03_method.tex", "04_unbound.tex"}


def test_l1_hedged_still_weakened_after_deixis_fix(tmp_path):
    """F9 guard rail: L1-bound categorical with hedge stays weakened_strong."""
    sec = _sections(
        tmp_path,
        {"03_results.tex": "% @claim:E1\nOur model may reach 0.93 accuracy.\n"},
    )
    report = audit_strength_mismatch(sec, [E1])
    assert len(report["weakened_strong"]) == 1
    assert report["overclaimed_weak"] == []


# ------------------------------------------------- Phase 0 regression tests


def test_booktabs_table_block_binding_and_standalone_tables(tmp_path):
    m = _materials(tmp_path)
    (m / "res.csv").write_text(
        "method,acc,f1\nours,0.934,0.881\nbase,0.850,0.800\n",
        encoding="utf-8",
    )
    e_tab = {
        "id": "ETAB",
        "claim": "Table results.",
        "origin": "material:res.csv#L2-L3",
        "evidence_level": "L1",
        "boundary": "any",
        "conversions": ["round_2dp"],
    }
    tab_tex = (
        "% @claim:ETAB\n"
        "\\begin{table}[t]\n"
        "  \\centering\n"
        "  \\caption{Main results.}\n"
        "  \\label{tab:main}\n"
        "  \\begin{tabular}{lrr}\n"
        "    \\toprule\n"
        "    method & acc & f1 \\\\\n"
        "    \\midrule\n"
        "    ours & 0.93 & 0.88 \\\\\n"
        "    base & 0.85 & 0.80 \\\\\n"
        "    \\bottomrule\n"
        "  \\end{tabular}\n"
        "\\end{table}\n"
    )
    sec = _sections(tmp_path, {"04_exp.tex": "\\section{Experiments}\n" + tab_tex})
    assert audit_numbers(sec, [e_tab], m) == []
    report = audit_strength_mismatch(sec, [e_tab])
    assert report["overclaimed_weak"] == []

    # Fabricated cell inside table is still caught.
    bad_sec = _sections(
        tmp_path,
        {"04_exp.tex": tab_tex.replace("0.88", "0.99")},
    )
    v_bad = audit_numbers(bad_sec, [e_tab], m)
    assert any("0.99" in x for x in v_bad)

    # Standalone tables/*.tex audited via tables_dir.
    tab_dir = tmp_path / "tables"
    tab_dir.mkdir()
    (tab_dir / "t1.tex").write_text(tab_tex, encoding="utf-8")
    sec_clean = _sections(tmp_path, {"04_exp.tex": "\\section{Experiments}\nSee Table~\\ref{tab:main}.\n"})
    assert audit_numbers(sec_clean, [e_tab], m, tables_dir=tab_dir) == []


def test_inline_data_math_audited_while_symbolic_math_stays_excluded(tmp_path):
    m = _materials(tmp_path)
    (m / "stats.csv").write_text(
        "acc,speedup,delta,std\n0.934,1.8,12.4,0.3\n",
        encoding="utf-8",
    )
    ec = {
        "id": "EC",
        "claim": "Metrics.",
        "origin": "material:stats.csv#L2",
        "evidence_level": "L1",
        "boundary": "any",
        "conversions": ["x100_percent"],
    }
    good = (
        "% @claim:EC\n"
        "Achieves $93.4\\%$ accuracy at $1.8\\times$ speedup with $+12.4$ pts and $4.2 \\pm 0.3\\%$ gain.\n"
    )
    # 4.2 is fabricated; 93.4, 1.8, +12.4, 0.3 are in span.
    sec = _sections(tmp_path, {"03_res.tex": good})
    v = audit_numbers(sec, [ec], m)
    assert len(v) == 1 and "4.2" in v[0]

    # When 4.2 is fixed to 12.4 and symbolic math is present, 0 violations.
    (m / "stats2.csv").write_text(
        "acc,speedup,delta,mean,std\n0.934,1.8,12.4,4.2,0.3\n",
        encoding="utf-8",
    )
    ec2 = {**ec, "origin": "material:stats2.csv#L2"}
    ok_tex = (
        "% @claim:EC\n"
        "Achieves $93.4\\%$ accuracy at $1.8\\times$ speedup with $+12.4$ pts and $\\textbf{4.2} \\pm 0.3\\%$, "
        "where $\\alpha=.57$, $1e^{-3}$, \\(x_1 + 2 = 3\\), and \\[y_0 = 1\\].\n"
    )
    sec2 = _sections(tmp_path, {"03_res.tex": ok_tex})
    assert audit_numbers(sec2, [ec2], m) == []

    # Unmarked fabricated $99.9\%$ inline math MUST NOT escape!
    fab_sec = _sections(tmp_path, {"03_res.tex": "Our model achieves $99.9\\%$ accuracy.\n"})
    v_fab = audit_numbers(fab_sec, [ec2], m)
    assert len(v_fab) == 1 and "99.9" in v_fab[0]


def test_unit_suffixed_numbers_audited(tmp_path):
    m = _materials(tmp_path)
    (m / "hw.csv").write_text("params,speed,mem,fps,lat,samples\n70B,20x,16GB,120FPS,100ms,18K\n", encoding="utf-8")
    ehw = {
        "id": "EHW",
        "claim": "Hardware metrics.",
        "origin": "material:hw.csv#L2",
        "evidence_level": "L1",
        "boundary": "any",
    }
    sec = _sections(
        tmp_path,
        {
            "03_res.tex": (
                "% @claim:EHW\n"
                "Our 70B model runs 20x faster in 16GB at 120FPS (100ms) on 18K samples.\n"
                "Fabricated 999GB memory usage.\n"
            )
        },
    )
    v = audit_numbers(sec, [ehw], m)
    assert len(v) == 1 and "999" in v[0]


def test_latex_commands_identifiers_ranges_and_enumerations_no_false_positive(tmp_path):
    m = _materials(tmp_path)
    (m / "rng.csv").write_text("lo,hi\n4,7\n", encoding="utf-8")
    er = {
        "id": "ER",
        "claim": "Range.",
        "origin": "material:rng.csv#L2",
        "evidence_level": "L1",
        "boundary": "any",
    }
    tex = (
        "\\section{Experiments}\n"
        "\\begin{figure}[t]\n"
        "  \\centering\n"
        "  \\includegraphics[width=0.8\\linewidth]{figures/fig-1.pdf}\n"
        "  \\caption{Training convergence.}\n"
        "  \\label{fig:conv}\n"
        "\\end{figure}\n"
        "\\vspace{0.5em}\n"
        "As shown in \\cref{fig:conv} and \\autoref{tab:main}, we use ResNet-50, CIFAR-100, GPT-4, and Llama-3.1.\n"
        "Our contributions are: (1) an encoder; (2) an analysis; (3) a benchmark.\n"
        "% @claim:ER\n"
        "As shown in Tab.~\\ref{tab:main}, our method gains 4--7 points.\n"
    )
    sec = _sections(tmp_path, {"03_res.tex": tex})
    assert audit_numbers(sec, [er], m) == []


def test_chained_conversions_and_numerical_equivalence(tmp_path):
    m = _materials(tmp_path)
    (m / "prec.csv").write_text("a,b,c\n0.9341,0.850,0.5\n", encoding="utf-8")
    ep = {
        "id": "EP",
        "claim": "Precision metrics.",
        "origin": "material:prec.csv#L2",
        "evidence_level": "L1",
        "boundary": "any",
        "conversions": ["x100_percent", "round_1dp", "round_0dp", "round_3dp"],
    }
    sec = _sections(
        tmp_path,
        {
            "a.tex": "% @claim:EP\nAccuracy is 93.4%, baseline is 0.85, rounded is 0.934 and 1.\n",
            "b.tex": "% @claim:EP\nDirection flip is -0.5.\n",
        },
    )
    v = audit_numbers(sec, [ep], m)
    assert len(v) == 1 and "b.tex" in v[0] and "-0.5" in v[0]


def test_chinese_sentence_splitting_prevents_silent_binding(tmp_path):
    m = _materials(tmp_path)
    sec = _sections(
        tmp_path,
        {
            "03_res.tex": (
                "% @claim:E1\n"
                "第一句取得 0.93 准确率。第二句编造 99.9 指标。\n"
            )
        },
    )
    v = audit_numbers(sec, [E1], m)
    assert len(v) == 1 and "99.9" in v[0] and "orphan" in v[0].lower()


def test_l3_whitelist_blocks_approach_experiments_abstract(tmp_path):
    m = _materials(tmp_path)
    sec = _sections(
        tmp_path,
        {
            "01_abs.tex": "\\section{Abstract}\n% @claim:E3\nWe extend \\cite{smith2023}.\n",
            "02_related.tex": "\\section{Background}\n% @claim:E3\nSmith et al. (2023) addressed graphs \\cite{smith2023}.\n",
            "03_approach.tex": "\\section{Approach}\n% @claim:E3\nWe follow \\cite{smith2023}.\n",
            "04_exp.tex": "\\section{Experiments}\n% @claim:E3\nEvaluated like \\cite{smith2023}.\n",
        },
    )
    v = audit_numbers(sec, [E3], m)
    flagged_files = {item.split(":")[0] for item in v}
    assert flagged_files == {"01_abs.tex", "03_approach.tex", "04_exp.tex"}


def test_l0_prose_proper_noun_check_and_strength_exclusion(tmp_path):
    m = _materials(tmp_path)
    k1 = {
        "id": "K1",
        "claim": "Neural networks are widely used.",
        "origin": "field_common",
        "evidence_level": "L0",
        "boundary": "directional",
    }
    sec_ok = _sections(tmp_path, {"01_intro.tex": "% @claim:K1\nNeural networks are widely used.\n"})
    assert audit_numbers(sec_ok, [k1], m) == []
    assert audit_strength_mismatch(sec_ok, [k1])["overclaimed_weak"] == []

    sec_bad = _sections(tmp_path, {"01_intro.tex": "% @claim:K1\nImageNet benchmarks are widely used.\n"})
    v = audit_numbers(sec_bad, [k1], m)
    assert len(v) == 1 and "ImageNet" in v[0]


def test_bib_cross_check_catches_unledgered_and_unbound_l3(tmp_path):
    m = _materials(tmp_path)
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@inproceedings{smith2023, title={G}, author={Smith}, year={2023}}\n"
        "@article{rogue2024, title={R}, author={Rogue}, year={2024}}\n",
        encoding="utf-8",
    )
    sec = _sections(
        tmp_path,
        {
            "02_related.tex": "\\section{Related Work}\n% @claim:E3\nSmith et al. (2023) addressed graphs \\cite{smith2023}.\n",
            "03_method.tex": "\\section{Approach}\nWe borrow \\cite{smith2023} and \\cite{rogue2024} and \\cite{ghost2025}.\n",
        },
    )
    v = audit_numbers(sec, [E3], m, bib_path=bib)
    assert any("rogue2024" in x and "unledgered" in x for x in v)
    assert any("ghost2025" in x and "not found" in x for x in v)
    assert any("smith2023" in x and "L3-only" in x for x in v)

    ledger = _ledger(tmp_path, [E3])
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(ledger), "--materials", str(m), "--sections", str(sec), "--bib", str(bib)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1


def test_canonical_l3_deixis_supports_single_dual_and_cvpr_styles(tmp_path):
    e_s = {**E3, "id": "ES", "origin": "retrieval:smith2023"}
    e_d = {**E3, "id": "ED", "origin": "retrieval:sj2023"}
    sec = _sections(
        tmp_path,
        {
            "02_related.tex": (
                "\\section{Related Work}\n"
                "% @claim:ES\n"
                "Smith (2023) studied graph classification \\cite{smith2023}.\n\n"
                "% @claim:ED\n"
                "Smith and Jones (2023) proposed graph kernels \\cite{sj2023}.\n\n"
                "% @claim:ES\n"
                "Smith et al.~\\cite{smith2023} addressed graph classification.\n"
            ),
        },
    )
    report = audit_strength_mismatch(sec, [e_s, e_d])
    assert report["overclaimed_weak"] == []
    # Mismatched citekey between @claim and prose must still be flagged.
    sec_mis = _sections(
        tmp_path,
        {
            "02_related.tex": (
                "\\section{Related Work}\n"
                "% @claim:ES\n"
                "Smith (2023) studied graph classification \\cite{sj2023}.\n"
            )
        },
    )
    assert len(audit_strength_mismatch(sec_mis, [e_s, e_d])["overclaimed_weak"]) == 1


# ------------------------------------------------- Phase 1 regression tests


def test_structural_signposts_filtered_from_overclaimed_weak(tmp_path):
    sec = _sections(
        tmp_path,
        {
            "01_intro.tex": (
                "In this section, we describe our formulation.\n"
                "The remainder of this paper is organized as follows.\n"
                "Section~\\ref{sec:method} presents the architecture.\n"
                "Figure~\\ref{fig:overview} illustrates the pipeline.\n"
                "Our method proves universal optimality.\n"
            )
        },
    )
    report = audit_strength_mismatch(sec, [])
    assert len(report["overclaimed_weak"]) == 1
    assert "proves universal optimality" in report["overclaimed_weak"][0]["sentence"]


def test_dispositions_persistence_suppresses_and_resurfaces_on_edit(tmp_path):
    m = _materials(tmp_path)
    ledger = _ledger(tmp_path, [E1])
    sec = _sections(
        tmp_path,
        {"03_results.tex": "% @claim:E1\nOur model may reach 0.93 accuracy.\n"},
    )
    r1 = audit_strength_mismatch(sec, [E1])
    assert len(r1["weakened_strong"]) == 1
    fp = r1["weakened_strong"][0]["fingerprint"]
    assert fp

    disp = tmp_path / "dispositions.json"
    # Incomplete disposition (missing rationale) does NOT suppress.
    disp.write_text(json.dumps([{"fingerprint": fp, "decision": "keep"}]), encoding="utf-8")
    r_incomplete = audit_strength_mismatch(sec, [E1], dispositions_path=disp)
    assert len(r_incomplete["weakened_strong"]) == 1

    # Complete disposition suppresses the item and records fingerprint.
    disp.write_text(
        json.dumps([{"fingerprint": fp, "decision": "keep", "rationale": "scope uncertainty"}]),
        encoding="utf-8",
    )
    r_suppressed = audit_strength_mismatch(sec, [E1], dispositions_path=disp)
    assert r_suppressed["weakened_strong"] == []
    assert r_suppressed["disposed_fingerprints"] == [fp]

    # CLI works cleanly with --dispositions.
    cli_ok = subprocess.run(
        [
            sys.executable, str(SCRIPT), str(ledger),
            "--materials", str(m), "--sections", str(sec),
            "--strength-report", "--dispositions", str(disp),
        ],
        capture_output=True, text=True,
    )
    assert cli_ok.returncode == 0
    assert fp in cli_ok.stdout

    # Editing the sentence invalidates the fingerprint -> resurfaces.
    (sec / "03_results.tex").write_text(
        "% @claim:E1\nOur approach could reach 0.93 accuracy.\n", encoding="utf-8"
    )
    r_resurfaced = audit_strength_mismatch(sec, [E1], dispositions_path=disp)
    assert len(r_resurfaced["weakened_strong"]) == 1
    assert r_resurfaced["weakened_strong"][0]["fingerprint"] != fp


def test_audit_outline_validates_keys_claims_and_viz_plan(tmp_path):
    m = _materials(tmp_path)
    ledger = _ledger(tmp_path, [E1])
    good_outline = tmp_path / "outline.json"
    good_outline.write_text(
        json.dumps({
            "title": "Real Paper",
            "venue": "CVPR 2025",
            "metadata": {"authors": [{"name": "Alice Smith"}], "paper_id": "12"},
            "sections": [{"id": "res", "kind": "experiments", "claims": ["E1"], "purpose": "Report."}],
            "lit_strategy": {"queries": ["graph learning"], "must_contain": ["GNN"]},
            "viz_plan": {"figures": [{"id": "fig1", "source_section": "res", "kind": "plot", "data_ref": "materials/results.csv"}]},
        }),
        encoding="utf-8",
    )
    assert ledger_audit.audit_outline(good_outline, claims=[E1], materials_dir=m) == []

    r_ok = subprocess.run(
        [sys.executable, str(SCRIPT), str(ledger), "--materials", str(m), "--outline", str(good_outline)],
        capture_output=True, text=True,
    )
    assert r_ok.returncode == 0

    bad_outline = tmp_path / "bad_outline.json"
    bad_outline.write_text(
        json.dumps({
            "title": "Real Paper",
            "venue": "CVPR 2025",
            "sections": [
                {"id": "s1", "kind": "intro", "claims": ["MISSING_CLAIM"], "purpose": "Intro."},
                {"id": "s1", "kind": "method", "claims": [], "purpose": "Dup id."},
            ],
            "lit_strategy": {"queries": [], "must_contain": []},
            "viz_plan": {"figures": [{"id": "f1", "source_section": "ghost_sec", "kind": "plot", "data_ref": "materials/missing.csv"}]},
        }),
        encoding="utf-8",
    )
    v = ledger_audit.audit_outline(bad_outline, claims=[E1], materials_dir=m)
    assert any("MISSING_CLAIM" in x for x in v)
    assert any("duplicate section id" in x for x in v)
    assert any("lit_strategy.queries" in x for x in v)
    assert any("ghost_sec" in x for x in v)
    assert any("missing.csv" in x for x in v)

    r_bad = subprocess.run(
        [sys.executable, str(SCRIPT), str(ledger), "--materials", str(m), "--outline", str(bad_outline)],
        capture_output=True, text=True,
    )
    assert r_bad.returncode == 1
