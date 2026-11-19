"""Deterministic log-to-figure and log-to-booktabs CLI for the paper-orchestrator skill.

From-scratch implementation (NOT a port): upstream PaperOrchestra has no
deterministic log->plot code -- its Plotting agent is LLM-generated code run
via exec(). This module replaces that with a fixed, model-free pipeline.

Runtime dependency: ``matplotlib`` for plot mode only; ``--mode table`` is
100% stdlib-only. No LLM calls, no network access, no seaborn. Same input
twice -> byte-identical outputs (PDF CreationDate suppressed; no timestamps).

Library surface:
    plot_from_log(log_path: Path, spec: dict) -> list[Path]   # [.pdf, .png]
    build_figure(log_path: Path, spec: dict) -> Figure        # unsaved figure
    log_to_table(log_path: Path, spec: dict) -> str           # booktabs .tex

plot spec: x_col, y_cols (list), kind ("line"|"bar"), xlabel, ylabel, out_dir;
optional: title, name, labels (dict/list), yerr_cols (dict y->err), xscale,
yscale, xlim, ylim.
table spec: columns (list), caption, label, round (dict column -> decimals);
optional: star (bool -> table*), headers (dict), bold_best (dict col->max|min).

Input formats: .csv (header row) and .jsonl (one flat JSON object per line).

CLI:
    python plot_from_logs.py --mode plot  --log train_log.csv --spec plot.json
    python plot_from_logs.py --mode table --log train_log.csv --spec table.json --out tab.tex

A requested column that is absent raises ColumnError whose message lists the
actual column names found in the log (CLI: actionable stderr + exit 1).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

# Lazy-loaded for plot mode so --mode table works in pure stdlib environments.
matplotlib = None
plt = None

# Okabe-Ito colorblind-safe palette (8 colors) + dual-encoding cycles.
PALETTE = [
    "#0072B2",  # blue
    "#E69F00",  # orange
    "#009E73",  # bluish green
    "#D55E00",  # vermillion
    "#CC79A7",  # reddish purple
    "#56B4E9",  # sky blue
    "#F0E442",  # yellow
    "#000000",  # black
]
LINESTYLES = ("-", "--", "-.", ":")
MARKERS = ("o", "s", "^", "D", "v", "P", "X", "*")
HATCHES = ("", "//", "\\\\", "xx", "..", "++", "oo", "--")


def _ensure_matplotlib() -> None:
    """Import matplotlib lazily with headless Agg backend and publication style."""
    global matplotlib, plt
    if matplotlib is not None and plt is not None:
        return
    import matplotlib as _mpl
    _mpl.use("Agg")
    import matplotlib.pyplot as _plt  # noqa: E402
    _mpl.rcParams.update({
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 9,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "legend.frameon": False,
        "figure.dpi": 100,
    })
    matplotlib = _mpl
    plt = _plt


class ColumnError(ValueError):
    """A requested column is absent; the message lists the actual columns."""


def _die(msg: str) -> None:
    """Print an actionable message to stderr and exit non-zero (no bare traceback)."""
    print(msg, file=sys.stderr)
    raise SystemExit(1)


# --- log reading (CSV + JSONL) ----------------------------------------------

def _read_log(log_path: Path) -> tuple[list[str], list[dict]]:
    """Return (column names in file order, rows as dicts)."""
    suffix = log_path.suffix.lower()
    if suffix == ".csv":
        with open(log_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            columns = list(reader.fieldnames or [])
            rows = list(reader)
    elif suffix == ".jsonl":
        rows = []
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
        columns = list(dict.fromkeys(k for row in rows for k in row))
    else:
        raise ValueError(f"unsupported log format {suffix!r} (expected .csv or .jsonl)")
    if not rows:
        raise ValueError(f"{log_path.name}: log has no data rows")
    return columns, rows


def _require_columns(columns: list[str], needed: list[str], log_path: Path) -> None:
    missing = [c for c in needed if c not in columns]
    if missing:
        raise ColumnError(
            f"{log_path.name}: column(s) not found: {', '.join(missing)}; "
            f"actual columns: {', '.join(columns)}"
        )


def _cell(row: dict, col: str, columns: list[str], log_path: Path):
    """Row access that turns a ragged-log KeyError into an actionable
    ColumnError (JSONL rows may omit keys other rows carry)."""
    try:
        return row[col]
    except KeyError:
        raise ColumnError(
            f"{log_path.name}: column {col!r} missing from a data row "
            f"(ragged log); actual columns: {', '.join(columns)}"
        ) from None


def _as_floats(values: list) -> list[float] | None:
    """All values as float, or None if any value is non-numeric."""
    try:
        return [float(v) for v in values]
    except (TypeError, ValueError):
        return None


# --- figures -----------------------------------------------------------------

def _series_label(labels_spec, idx: int, col: str) -> str:
    if isinstance(labels_spec, dict):
        return str(labels_spec.get(col, col))
    if isinstance(labels_spec, list) and idx < len(labels_spec):
        return str(labels_spec[idx])
    return col


def build_figure(log_path: Path, spec: dict):
    """Build (but do not save) the figure described by spec. Caller closes it."""
    _ensure_matplotlib()
    log_path = Path(log_path)
    kind = spec.get("kind", "line")
    if kind not in ("line", "bar"):
        raise ValueError(f"spec.kind must be 'line' or 'bar', got {kind!r}")
    x_col = spec["x_col"]
    y_cols = list(spec["y_cols"])
    if not y_cols:
        raise ValueError("spec.y_cols must be a non-empty list")
    yerr_cols = spec.get("yerr_cols") or {}
    if not isinstance(yerr_cols, dict):
        raise ValueError("spec.yerr_cols must be a dict mapping y_col -> err_col")
    needed = [x_col, *y_cols, *yerr_cols.values()]
    columns, rows = _read_log(log_path)
    _require_columns(columns, needed, log_path)

    x_raw = [_cell(r, x_col, columns, log_path) for r in rows]
    x = _as_floats(x_raw)
    if x is None:
        x = x_raw  # categorical axis (bar labels / string ticks)
    series = []
    for col in y_cols:
        ys = _as_floats([_cell(r, col, columns, log_path) for r in rows])
        if ys is None:
            raise ValueError(f"{log_path.name}: column {col!r} contains non-numeric values")
        series.append(ys)
    errs_by_col: dict[str, list[float]] = {}
    for y_col, err_col in yerr_cols.items():
        es = _as_floats([_cell(r, err_col, columns, log_path) for r in rows])
        if es is None:
            raise ValueError(f"{log_path.name}: error column {err_col!r} contains non-numeric values")
        errs_by_col[y_col] = es

    n = len(rows)
    labels_spec = spec.get("labels")
    fig, ax = plt.subplots(figsize=(4.8, 3.2) if kind == "bar" else (4.0, 3.0))
    for i, (col, ys) in enumerate(zip(y_cols, series)):
        color = PALETTE[i % len(PALETTE)]
        lbl = _series_label(labels_spec, i, col)
        errs = errs_by_col.get(col)
        if kind == "line":
            ls = LINESTYLES[i % len(LINESTYLES)]
            mk = MARKERS[i % len(MARKERS)]
            markevery = max(1, n // 20) if n > 40 else None
            ax.plot(
                x,
                ys,
                color=color,
                linestyle=ls,
                label=lbl,
                linewidth=1.6,
                marker=mk,
                markersize=3,
                markevery=markevery,
            )
            if errs is not None:
                lo = [y - e for y, e in zip(ys, errs)]
                hi = [y + e for y, e in zip(ys, errs)]
                ax.fill_between(x, lo, hi, color=color, alpha=0.18, linewidth=0)
        else:
            width = 0.8 / len(y_cols)
            offsets = [j + (i - (len(y_cols) - 1) / 2) * width for j in range(n)]
            hatch = HATCHES[i % len(HATCHES)]
            edgecolor = "#000000" if hatch else "none"
            bar_kw = {}
            if errs is not None:
                bar_kw = {"yerr": errs, "error_kw": {"ecolor": "#000000", "capsize": 2}}
            ax.bar(
                offsets,
                ys,
                width=width,
                color=color,
                edgecolor=edgecolor,
                hatch=hatch,
                label=lbl,
                **bar_kw,
            )

    if kind == "bar":
        stride = max(1, math.ceil(n / 10))
        ticks = list(range(0, n, stride))
        ax.set_xticks(ticks)
        ax.set_xticklabels([str(x_raw[j]) for j in ticks], rotation=45, ha="right")

    ax.set_xlabel(spec.get("xlabel") or x_col)
    if spec.get("ylabel"):
        ax.set_ylabel(spec["ylabel"])
    if spec.get("title"):
        ax.set_title(spec["title"])
    if spec.get("xscale"):
        ax.set_xscale(spec["xscale"])
    if spec.get("yscale"):
        ax.set_yscale(spec["yscale"])
    if spec.get("xlim"):
        ax.set_xlim(*spec["xlim"])
    if spec.get("ylim"):
        ax.set_ylim(*spec["ylim"])
    if len(y_cols) > 1:
        ax.legend(loc="best", frameon=False)
    if kind == "line":
        ax.margins(x=0.02)
    fig.tight_layout()
    return fig


def plot_from_log(log_path: Path, spec: dict) -> list[Path]:
    """Render spec to out_dir as <name>.pdf (vector) + <name>.png (300dpi preview).

    Returns [pdf_path, png_path]. Deterministic: the PDF CreationDate is
    suppressed so repeated runs on the same input are byte-identical.
    """
    _ensure_matplotlib()
    log_path = Path(log_path)
    out_dir = Path(spec["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = spec.get("name") or log_path.stem
    fig = build_figure(log_path, spec)
    pdf_path = out_dir / f"{stem}.pdf"
    png_path = out_dir / f"{stem}.png"
    try:
        fig.savefig(pdf_path, bbox_inches="tight", pad_inches=0.05,
                    metadata={"Creator": "plot_from_logs", "CreationDate": None})
        fig.savefig(png_path, dpi=300, bbox_inches="tight", pad_inches=0.05)
    finally:
        plt.close(fig)
    return [pdf_path, png_path]


# --- booktabs tables ----------------------------------------------------------

_LATEX_ESCAPE = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def _latex_escape(s: str) -> str:
    return re.sub(r"[\\&%$#_{}~^]", lambda m: _LATEX_ESCAPE[m.group()], s)


def _format_cell(value, decimals: int | None) -> str:
    if value is None:
        raise ValueError("null value in log cell")
    if decimals is None:
        return str(value)
    return f"{float(value):.{decimals}f}"


def log_to_table(log_path: Path, spec: dict) -> str:
    """Render selected columns as a complete booktabs table block (LaTeX str).

    spec: columns (list), caption, label, round (dict column -> decimals);
    optional: star (bool -> table*), headers (dict col->display), bold_best
    (dict col->"max"|"min"). Numeric columns are right-aligned; headers and
    cells are LaTeX-escaped. caption/label are treated as raw LaTeX.
    """
    log_path = Path(log_path)
    columns, rows = _read_log(log_path)
    wanted = list(spec["columns"])
    if not wanted:
        raise ValueError("spec.columns must be a non-empty list")
    _require_columns(columns, wanted, log_path)
    rounding = dict(spec.get("round") or {})
    headers = dict(spec.get("headers") or {})
    bold_best = dict(spec.get("bold_best") or {})

    best_vals: dict[str, float] = {}
    for col, mode in bold_best.items():
        if mode not in ("max", "min"):
            raise ValueError(f"spec.bold_best[{col!r}] must be 'max' or 'min', got {mode!r}")
        if col not in wanted:
            raise ColumnError(
                f"{log_path.name}: bold_best column {col!r} not in spec.columns; "
                f"actual columns: {', '.join(columns)}"
            )
        vals = _as_floats([_cell(r, col, columns, log_path) for r in rows])
        if vals is None:
            raise ValueError(f"{log_path.name}: bold_best column {col!r} is non-numeric")
        best_vals[col] = max(vals) if mode == "max" else min(vals)

    align = []
    for col in wanted:
        numeric = _as_floats([_cell(r, col, columns, log_path) for r in rows]) is not None
        align.append("r" if numeric else "l")

    env = "table*" if spec.get("star") else "table"
    lines = [f"\\begin{{{env}}}[t]", r"  \centering"]
    if spec.get("caption"):
        lines.append(f"  \\caption{{{spec['caption']}}}")
    if spec.get("label"):
        lines.append(f"  \\label{{{spec['label']}}}")
    lines.append(f"  \\begin{{tabular}}{{{''.join(align)}}}")
    lines.append(r"    \toprule")
    lines.append(
        "    " + " & ".join(_latex_escape(str(headers.get(c, c))) for c in wanted) + r" \\"
    )
    lines.append(r"    \midrule")
    for r in rows:
        rendered: list[str] = []
        for c in wanted:
            raw_v = _cell(r, c, columns, log_path)
            escaped = _latex_escape(_format_cell(raw_v, rounding.get(c)))
            if c in best_vals and math.isclose(
                float(raw_v), best_vals[c], rel_tol=1e-12, abs_tol=1e-12
            ):
                escaped = f"\\textbf{{{escaped}}}"
            rendered.append(escaped)
        lines.append("    " + " & ".join(rendered) + r" \\")
    lines.append(r"    \bottomrule")
    lines.append(r"  \end{tabular}")
    lines.append(f"\\end{{{env}}}")
    return "\n".join(lines) + "\n"


# --- CLI -----------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Deterministic experiment-log -> publication figure (PDF+PNG) "
                    "or booktabs LaTeX table. Offline; matplotlib optional for table mode.",
    )
    parser.add_argument("--mode", required=True, choices=["plot", "table"],
                        help="plot: PDF+PNG figure; table: booktabs .tex")
    parser.add_argument("--log", required=True, help="input log (.csv or .jsonl)")
    parser.add_argument("--spec", required=True,
                        help="JSON file with the plot/table spec dict")
    parser.add_argument("--out", default=None,
                        help="table mode: output .tex path (default: stdout); "
                             "plot mode: overrides spec.out_dir")
    args = parser.parse_args(argv)

    log_path = Path(args.log)
    try:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _die(f"cannot read spec {args.spec}: {e}")
    if not isinstance(spec, dict):
        _die(f"spec {args.spec} must be a JSON object")
    if args.out and args.mode == "plot":
        spec["out_dir"] = args.out

    try:
        if args.mode == "plot":
            if not spec.get("out_dir"):
                _die("plot mode needs spec.out_dir (or --out DIR)")
            paths = plot_from_log(log_path, spec)
            print("wrote " + ", ".join(str(p) for p in paths), file=sys.stderr)
        else:
            tex = log_to_table(log_path, spec)
            if args.out:
                Path(args.out).write_text(tex, encoding="utf-8")
                print(f"wrote {args.out}", file=sys.stderr)
            else:
                sys.stdout.write(tex)
    except ColumnError as e:
        _die(str(e))
    except (ValueError, OSError, KeyError, TypeError, ImportError) as e:
        _die(f"{args.mode} failed for {args.log}: {e}")


if __name__ == "__main__":
    main()