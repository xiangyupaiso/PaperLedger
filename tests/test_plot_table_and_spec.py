"""Pure-stdlib tests for plot_from_logs.py (table mode, lazy matplotlib, spec validation)."""
import builtins
import json
from pathlib import Path

import pytest

import plot_from_logs as pfl

FIXTURE = Path(__file__).parent / "fixtures" / "demo_materials" / "train_log.csv"


def test_table_mode_runs_without_matplotlib(monkeypatch, tmp_path):
    real_import = builtins.__import__

    def block_mpl(name, *args, **kwargs):
        if name == "matplotlib" or name.startswith("matplotlib."):
            raise ModuleNotFoundError("blocked matplotlib for stdlib check")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_mpl)
    monkeypatch.setattr(pfl, "matplotlib", None)
    monkeypatch.setattr(pfl, "plt", None)

    spec_file = tmp_path / "tab.json"
    spec_file.write_text(
        json.dumps({
            "columns": ["step", "val_acc"],
            "caption": "No matplotlib.",
            "label": "tab:nompl",
            "round": {"val_acc": 2},
        }),
        encoding="utf-8",
    )
    out_tex = tmp_path / "tab.tex"
    pfl.main(["--mode", "table", "--log", str(FIXTURE), "--spec", str(spec_file), "--out", str(out_tex)])
    tex = out_tex.read_text(encoding="utf-8")
    assert r"\toprule" in tex and r"\bottomrule" in tex


def test_table_star_headers_and_bold_best(tmp_path):
    log = tmp_path / "cmp.csv"
    log.write_text(
        "method_name,acc_score,err_rate\n"
        "baseline,0.851,0.149\n"
        "ours_v1,0.934,0.066\n",
        encoding="utf-8",
    )
    tex = pfl.log_to_table(
        log,
        {
            "columns": ["method_name", "acc_score", "err_rate"],
            "caption": "Comparison.",
            "label": "tab:cmp",
            "star": True,
            "headers": {"method_name": "Method", "acc_score": "Acc (%)", "err_rate": "Err"},
            "round": {"acc_score": 2, "err_rate": 3},
            "bold_best": {"acc_score": "max", "err_rate": "min"},
        },
    )
    assert r"\begin{table*}[t]" in tex
    assert r"\end{table*}" in tex
    assert r"Method & Acc (\%) & Err \\" in tex
    assert r"ours\_v1 & \textbf{0.93} & \textbf{0.066} \\" in tex
    assert r"baseline & 0.85 & 0.149 \\" in tex


def test_cli_missing_spec_key_and_null_cell_clean_error(tmp_path, capsys):
    bad_jsonl = tmp_path / "nulls.jsonl"
    bad_jsonl.write_text(json.dumps({"step": 1, "acc": None}) + "\n", encoding="utf-8")
    spec = tmp_path / "tab_spec.json"
    spec.write_text(json.dumps({"columns": ["step", "acc"]}), encoding="utf-8")
    with pytest.raises(SystemExit) as exc1:
        pfl.main(["--mode", "table", "--log", str(bad_jsonl), "--spec", str(spec)])
    assert exc1.value.code != 0
    err1 = capsys.readouterr().err
    assert "null" in err1.lower() and "Traceback" not in err1

    # Missing required key ("columns") in table spec -> clean stderr, no traceback
    bad_spec = tmp_path / "missing_key.json"
    bad_spec.write_text(json.dumps({"caption": "Oops"}), encoding="utf-8")
    with pytest.raises(SystemExit) as exc2:
        pfl.main(["--mode", "table", "--log", str(FIXTURE), "--spec", str(bad_spec)])
    assert exc2.value.code != 0
    err2 = capsys.readouterr().err
    assert "columns" in err2 and "Traceback" not in err2


def test_dual_encoding_constants_contract():
    assert len(pfl.PALETTE) == 8
    assert len(pfl.LINESTYLES) >= 4
    assert len(pfl.MARKERS) >= 6
    assert len(pfl.HATCHES) >= 6
