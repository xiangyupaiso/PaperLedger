"""Tests for plot_from_logs.py (Task 4, from-scratch -- no upstream equivalent).

The six mandated tests pin the deterministic log->figure / log->booktabs
behaviour; a seventh covers the ``--mode plot|table`` CLI. Everything runs
offline against the fixed 20-row fixture ``demo_materials/train_log.csv``.
"""
import csv
import json
import socket
from pathlib import Path

import pytest
from matplotlib.colors import to_hex

import plot_from_logs as pfl

FIXTURE = Path(__file__).parent / "fixtures" / "demo_materials" / "train_log.csv"
ACTUAL_COLS = ["step", "loss", "acc", "val_loss", "val_acc"]

# Canonical Okabe-Ito colorblind-safe palette (8 colors), pinned independently
# of the module constant so a wrong PALETTE cannot pass by self-reference.
OKABE_ITO = {
    "#000000", "#E69F00", "#56B4E9", "#009E73",
    "#F0E442", "#0072B2", "#D55E00", "#CC79A7",
}


def line_spec(out_dir, y_cols=("loss", "val_loss")):
    return {
        "x_col": "step",
        "y_cols": list(y_cols),
        "kind": "line",
        "xlabel": "Training step",
        "ylabel": "Loss",
        "title": "Training curves",
        "out_dir": str(out_dir),
    }


def fixture_rows():
    with open(FIXTURE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# --- 1. line spec emits vector PDF + 300dpi PNG, both >1KB, deterministic --

def test_line_spec_emits_pdf_and_png(tmp_path):
    out_a = tmp_path / "a"
    paths = pfl.plot_from_log(FIXTURE, line_spec(out_a))
    assert len(paths) == 2
    assert {p.suffix for p in paths} == {".pdf", ".png"}
    for p in paths:
        assert p.exists() and p.stat().st_size > 1024, f"{p} missing or <=1KB"

    # Style constants pinned by the plan: >=9pt fonts, embedded TrueType in PDF.
    assert pfl.matplotlib.rcParams["font.size"] >= 9
    assert pfl.matplotlib.rcParams["pdf.fonttype"] == 42

    # Deterministic: same input twice -> byte-identical outputs (no timestamps).
    out_b = tmp_path / "b"
    paths_b = pfl.plot_from_log(FIXTURE, line_spec(out_b))
    for pa, pb in zip(paths, paths_b):
        assert pa.read_bytes() == pb.read_bytes(), f"{pa.name} not byte-identical"


# --- 2. booktabs table with per-column rounding -----------------------------

def test_table_mode_booktabs_and_round():
    spec = {
        "columns": ["step", "loss", "val_acc"],
        "caption": "Training summary.",
        "label": "tab:train",
        # Precision DIFFERS from the fixture's native 2dp/3dp: an implementation
        # that ignores `round` (str passthrough) cannot reproduce these cells.
        "round": {"loss": 1, "val_acc": 2},
    }
    tex = pfl.log_to_table(FIXTURE, spec)
    for rule in (r"\toprule", r"\midrule", r"\bottomrule"):
        assert rule in tex
    assert r"\caption{Training summary.}" in tex
    assert r"\label{tab:train}" in tex
    assert r"\begin{tabular}" in tex and r"\end{tabular}" in tex
    # underscores in headers are LaTeX-escaped
    assert r"val\_acc" in tex

    # exactly 20 data rows between \midrule and \bottomrule
    body = tex.split(r"\midrule")[1].split(r"\bottomrule")[0]
    data_lines = [ln.strip() for ln in body.splitlines() if ln.strip().endswith(r"\\")]
    assert len(data_lines) == 20

    # Per-cell exact checks (substring checks are non-discriminating: "2.3" is
    # a substring of the raw "2.31").
    rows = fixture_rows()
    cells = [[c.strip() for c in ln[:-2].split("&")] for ln in data_lines]
    for r, (step_cell, loss_cell, val_acc_cell) in zip(rows, cells):
        # unrounded column passes through verbatim, as an exact cell
        assert step_cell == r["step"]
        # rounded to the requested precision, as an exact cell
        assert loss_cell == f"{float(r['loss']):.1f}"
        assert val_acc_cell == f"{float(r['val_acc']):.2f}"
        # the raw fixture forms must NOT survive in the rounded columns
        assert loss_cell != r["loss"]
        assert val_acc_cell != r["val_acc"]
    assert cells[0][0] == "100" and cells[-1][0] == "2000"


# --- 3. ColumnError lists the actual column names ---------------------------

def test_missing_column_error_lists_actual_columns(tmp_path):
    bad_plot = line_spec(tmp_path, y_cols=("loss", "accuracy"))
    with pytest.raises(pfl.ColumnError) as exc:
        pfl.plot_from_log(FIXTURE, bad_plot)
    msg = str(exc.value)
    assert "accuracy" in msg
    for col in ACTUAL_COLS:
        assert col in msg, f"actual column {col!r} not listed in: {msg}"

    bad_table = {"columns": ["step", "bogus"], "caption": "c", "label": "tab:c"}
    with pytest.raises(pfl.ColumnError) as exc:
        pfl.log_to_table(FIXTURE, bad_table)
    msg = str(exc.value)
    assert "bogus" in msg
    for col in ACTUAL_COLS:
        assert col in msg


# --- 4. every artist color comes from the Okabe-Ito PALETTE constant --------

def test_palette_is_colorblind_safe(tmp_path):
    assert len(pfl.PALETTE) == 8
    assert {c.upper() for c in pfl.PALETTE} == OKABE_ITO
    allowed = {to_hex(c).upper() for c in pfl.PALETTE}

    def check(fig):
        n_artists = 0
        for ax in fig.axes:
            for line in ax.get_lines():
                assert to_hex(line.get_color()).upper() in allowed
                n_artists += 1
            for patch in ax.patches:
                assert to_hex(patch.get_facecolor()).upper() in allowed
                edge = patch.get_edgecolor()
                if to_hex(edge) != "none":
                    assert to_hex(edge).upper() in allowed
                n_artists += 1
        assert n_artists > 0
        pfl.plt.close(fig)

    # line kind: 3 series -> 3 colored lines
    check(pfl.build_figure(FIXTURE, line_spec(tmp_path, y_cols=("loss", "acc", "val_acc"))))
    # bar kind: 2 series -> colored patches
    bar = line_spec(tmp_path, y_cols=("acc", "val_acc"))
    bar["kind"] = "bar"
    bar["ylabel"] = "Accuracy"
    check(pfl.build_figure(FIXTURE, bar))


# --- 5. JSONL input works alongside CSV -------------------------------------

def test_jsonl_input_supported(tmp_path):
    jsonl = tmp_path / "train_log.jsonl"
    with open(jsonl, "w", encoding="utf-8") as f:
        for r in fixture_rows():
            f.write(json.dumps({k: float(v) for k, v in r.items()}) + "\n")

    paths = pfl.plot_from_log(jsonl, line_spec(tmp_path / "figs"))
    assert {p.suffix for p in paths} == {".pdf", ".png"}
    for p in paths:
        assert p.stat().st_size > 1024

    tex = pfl.log_to_table(jsonl, {
        "columns": ["step", "loss"],
        "caption": "JSONL table.",
        "label": "tab:jsonl",
        "round": {"loss": 1},  # differs from the fixture's native 2dp
    })
    assert r"\toprule" in tex and r"\bottomrule" in tex
    body = tex.split(r"\midrule")[1].split(r"\bottomrule")[0]
    first = [ln.strip() for ln in body.splitlines() if ln.strip().endswith(r"\\")][0]
    cells = [c.strip() for c in first[:-2].split("&")]
    assert cells[1] == f"{float(fixture_rows()[0]['loss']):.1f}"


# --- 6. fully offline: socket stubbed to raise ------------------------------

def test_no_internet_required(tmp_path, monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("network access attempted during plotting")

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)

    paths = pfl.plot_from_log(FIXTURE, line_spec(tmp_path))
    assert all(p.stat().st_size > 1024 for p in paths)
    tex = pfl.log_to_table(FIXTURE, {
        "columns": ["step", "acc"], "caption": "Offline.", "label": "tab:off",
        "round": {"acc": 3},
    })
    assert r"\midrule" in tex


# --- 7. CLI: --mode plot|table on one file ----------------------------------

def test_cli_modes(tmp_path, capsys):
    plot_spec_file = tmp_path / "plot_spec.json"
    plot_spec_file.write_text(json.dumps(line_spec(tmp_path / "cli_figs")), encoding="utf-8")
    pfl.main(["--mode", "plot", "--log", str(FIXTURE), "--spec", str(plot_spec_file)])
    assert (tmp_path / "cli_figs" / "train_log.pdf").stat().st_size > 1024
    assert (tmp_path / "cli_figs" / "train_log.png").stat().st_size > 1024

    table_spec_file = tmp_path / "table_spec.json"
    table_spec_file.write_text(json.dumps({
        "columns": ["step", "loss"], "caption": "CLI table.",
        "label": "tab:cli", "round": {"loss": 2},
    }), encoding="utf-8")
    out_tex = tmp_path / "table.tex"
    pfl.main(["--mode", "table", "--log", str(FIXTURE),
              "--spec", str(table_spec_file), "--out", str(out_tex)])
    assert r"\toprule" in out_tex.read_text(encoding="utf-8")

    # missing column via CLI -> actionable non-zero exit listing actual columns
    bad_spec_file = tmp_path / "bad_spec.json"
    bad_spec_file.write_text(json.dumps(line_spec(tmp_path, y_cols=("nope",))), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        pfl.main(["--mode", "plot", "--log", str(FIXTURE), "--spec", str(bad_spec_file)])
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "nope" in err
    for col in ACTUAL_COLS:
        assert col in err

# --- 8. CLI: ValueError/OSError escape as actionable exits — fix-wave F12 ----

def test_cli_valueerror_and_oserror_actionable(tmp_path, capsys):
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(line_spec(tmp_path / "figs")), encoding="utf-8")

    # empty log (header only) -> ValueError 'no data rows'
    empty = tmp_path / "empty.csv"
    empty.write_text("step,loss\n", encoding="utf-8")
    # bad suffix -> ValueError 'unsupported log format'
    bad_suffix = tmp_path / "log.txt"
    bad_suffix.write_text("step,loss\n1,2\n", encoding="utf-8")
    # missing file -> OSError
    missing = tmp_path / "absent.csv"

    for log, needle in ((empty, "no data rows"), (bad_suffix, "unsupported"),
                        (missing, "absent.csv")):
        with pytest.raises(SystemExit) as exc:
            pfl.main(["--mode", "plot", "--log", str(log), "--spec", str(spec_file)])
        assert exc.value.code != 0
        err = capsys.readouterr().err
        assert needle in err, (log, err)
        assert "Traceback" not in err

    # bad kind -> ValueError
    bad_kind = dict(line_spec(tmp_path / "figs"), kind="scatter")
    spec_file.write_text(json.dumps(bad_kind), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        pfl.main(["--mode", "plot", "--log", str(FIXTURE), "--spec", str(spec_file)])
    assert exc.value.code != 0
    assert "kind" in capsys.readouterr().err


# --- 9. ragged JSONL row missing a key -> ColumnError — fix-wave F12 ---------

def test_ragged_jsonl_missing_key_columnerror(tmp_path, capsys):
    ragged = tmp_path / "ragged.jsonl"
    ragged.write_text(
        json.dumps({"step": 1, "loss": 2.0}) + "\n"
        + json.dumps({"step": 2}) + "\n",  # 'loss' missing on row 2
        encoding="utf-8",
    )
    with pytest.raises(pfl.ColumnError) as exc:
        pfl.plot_from_log(ragged, line_spec(tmp_path / "figs", y_cols=("loss",)))
    msg = str(exc.value)
    assert "loss" in msg
    assert "step" in msg, "actual columns must be listed"

    # table mode hits the same guard
    with pytest.raises(pfl.ColumnError):
        pfl.log_to_table(ragged, {"columns": ["step", "loss"]})

    # CLI surfaces it as an actionable exit, not a KeyError traceback
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(
        json.dumps(line_spec(tmp_path / "figs", y_cols=("loss",))), encoding="utf-8"
    )
    with pytest.raises(SystemExit) as exc:
        pfl.main(["--mode", "plot", "--log", str(ragged), "--spec", str(spec_file)])
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "loss" in err and "Traceback" not in err
