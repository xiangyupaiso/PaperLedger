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
    """F9: 'X et al. (Year) addressed Y \cite{...}' bound to L3 in related
    work is exactly what L3 semantics supports -> NOT overclaimed_weak."""
    sec = _sections(
        tmp_path,
        {
            "01_related.tex": (
                "\section{Related Work}\n"
                "% @claim:E3\n"
                "Smith et al. (2023) addressed graph classification "
                "\cite{smith2023}.\n"
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
                "\section{Related Work}\n"
                "% @claim:E3\n"
                # deixis shape BUT a performance number -> still flagged
                "Smith et al. (2023) studied graph classification and reached "
                "0.95 accuracy \cite{smith2023}.\n"
            ),
            "02_other.tex": (
                "\section{Discussion}\n"
                "% @claim:E3\n"
                # categorical assertion, no deixis shape -> still flagged
                "Graph classification is solved \cite{smith2023}.\n"
            ),
            "03_method.tex": (
                "\section{Method}\n"
                "% @claim:E3\n"
                # canonical shape but in a methods section -> still flagged
                "Smith et al. (2023) addressed graph classification "
                "\cite{smith2023}.\n"
            ),
            "04_unbound.tex": (
                "\section{Intro}\n"
                # canonical shape but unbound -> still flagged
                "Smith et al. (2023) addressed graph classification "
                "\cite{smith2023}.\n"
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
