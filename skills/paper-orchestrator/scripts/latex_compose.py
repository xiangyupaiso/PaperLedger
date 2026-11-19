# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Adapted 2026-11-17; see references/vendor-notices.md
# Ported from upstream @d9bae997 (PaperOrchestra):
#   - template staging via shutil.copytree(..., dirs_exist_ok=True)
#     (methods/paper_writer.py:68; figures staging likewise :55);
#   - compile_latex: the pdflatex -> bibtex -> pdflatex -> pdflatex sequence
#     (utils/pdf_utils.py:180-185, function head :169), the TeX env-var scrub
#     (:176-178), capture_output/timeout subprocess handling (:192-215) and
#     the "PDF exists and no TIMEOUT" success rule (:217-221).
#     Changes: stdlib only (rich printing dropped), per-command timeout raised
#     30s -> 120s, engine is a parameter, PDF stays in the staging dir (no
#     shutil.move to an external path), logs are returned instead of printed.
# NEW work, no upstream counterpart (verified in vendor-notices.md 二.4):
#   \input wiring (marker path + real-conference no-marker path per the
#   Task 2 structure memo), % @claim: marker stripping, to_cites numeric
#   citation bridge, the ComposeReport integrity checks, and the
#   latexmk -> xelatex -> pdflatex toolchain probe.

"""Assemble sections + bib + figures into a submission-ready LaTeX package.

Runtime dependencies: stdlib ONLY (argparse/json/os/re/shutil/subprocess/
pathlib/dataclasses). No LLM calls.

Library surface:
    compose(template_dir, sections_dir, bib_path, figures_dir, out_dir,
            numeric_map=None, tables_dir=None, outline_path=None) -> ComposeReport
    to_cites(tex, numeric_map) -> str        # [n]/[n,m]/[n-m] -> \\cite{key}
    CiteError                                # missing / out-of-range number
    ComposeReport.ok                         # False on any integrity violation
                                             # or a failed compile; None
                                             # (no TeX installed) does not fail

Wiring rules:
    - entry file: main.tex if present, else template.tex (upstream cvpr2025
      ships template.tex; there is no main.tex upstream);
    - if the entry carries the marker line
      ``% >>> paper-orchestrator: sections`` -> \\input lines inserted right
      below it, in section filename order;
    - no marker (the real-conference norm) -> per the Task 2 structure memo
      (references/vendor-notices.md 四): replace the example body between the
      first \\maketitle and the ``{`` opening the \\small bibliography block;
      bibliography block, commented appendix and \\end{document} are kept.

Draft conventions honored: ``% @claim:<id>`` comment lines (Task 6) are
stripped from the assembled manuscript. numeric_map duplicate values (several
numbers -> one citekey) are legal multi-point citations: warning only (R1).

CLI:
    python latex_compose.py --template DIR --sections DIR --bib refs.bib \
        --figures DIR --out manuscript/ [--tables DIR] [--outline outline.json] \
        [--numeric-map map.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

MARKER = "% >>> paper-orchestrator: sections"
CLAIM_LINE = re.compile(r"^\s*%\s*@claim:")
NUM_GROUP = re.compile(r"\[(\d+(?:\s*(?:,|--|-)\s*\d+)*)\]")
# Regions where a bare [digit] group is NOT a draft citation: math spans
# (display env, $...$, $$...$$, \(...\), \[...\]), comments, \cite optional
# args, and LaTeX macro/item/linebreak optional args.
MATH_SPAN_RE = re.compile(
    r"\\begin\{(equation|align|gather|multline|flalign|eqnarray)\*?\}.*?\\end\{\1\*?\}"
    r"|(?<!\\)\$\$.*?(?<!\\)\$\$"
    r"|(?<!\\)\$[^$]*?(?<!\\)\$"
    r"|\\\(.*?\\\)"
    r"|\\\[.*?\\\]",
    re.DOTALL,
)
COMMENT_SPAN_RE = re.compile(r"(?<!\\)%[^\n]*")
CITE_OPT_RE = re.compile(
    r"\\(?:cite[a-z]*|parencite|textcite|autocite|footcite)\*?(?:\[[^\]]*\])+"
)
MACRO_OPT_RE = re.compile(
    r"\\(?:re|provide)?newcommand\*?(?:\{[^{}]*\}|\\[A-Za-z@]+)\s*\[\d+\]"
    r"|\\DeclareRobustCommand\*?(?:\{[^{}]*\}|\\[A-Za-z@]+)\s*\[\d+\]"
    r"|\\(?:re)?newenvironment\*?\{[^{}]*\}\s*\[\d+\]"
    r"|\\item\s*\[\d+\]"
    r"|\\\\\s*\[\d+(?:\.\d+)?\s*(?:pt|em|ex|mm|cm|in)?\]"
)
CITE_RE = re.compile(
    r"\\(?:cite[a-z]*|parencite|textcite|autocite|footcite)\*?(?:\[[^\]]*\])*\{([^}]*)\}"
)
INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
GRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
BIB_KEY_RE = re.compile(r"@\w+\s*\{\s*([^,\s{}]+)\s*,")
RASTER_EXTS = {".png", ".jpg", ".jpeg"}
GRAPHIC_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".eps")
# cvpr2025 author-kit placeholders that must be replaced before submission
# (vendor-notices.md 四: \title{My Title} :18, example author block :20-:24,
# \def\paperID{12345678} :13). Survival is a compose WARNING, never a failure.
CVPR_PLACEHOLDERS = (
    "\\title{My Title}",
    "Ambitious AI Researcher",
    "\\def\\paperID{12345678}",
)
_MAX_RANGE_EXPAND = 200


class CiteError(ValueError):
    """A [n] reference has no citekey in numeric_map (missing/out of range)."""


@dataclass
class ComposeReport:
    compiled: bool | None  # None = no TeX toolchain on this machine
    missing_citations: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    raster_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.compiled is not False
            and not self.missing_citations
            and not self.missing_files
            and not self.raster_refs
        )


def to_cites(tex: str, numeric_map: dict[str, str]) -> str:
    """Bridge numeric draft citations [n] / [n,m] / [n-m] to \\cite{key,...}.

    Every number must exist in numeric_map (keys are number strings "1"..);
    a missing, inverted, or out-of-range number raises CiteError. Several
    numbers mapping to the SAME citekey are legal (multi-point citation of
    one reference): keys are deduplicated inside the \\cite, no error is raised.

    Guards: [digit] groups inside math spans (display environments, $...$,
    $$...$$, \\(...\\), \\[...\\]), % comments, \\cite-variant optional args,
    and macro/item/linebreak optional args are left untouched. Each prose
    conversion emits one stderr warning line listing what was bridged.
    """
    protected = [
        (m.start(), m.end())
        for rx in (MATH_SPAN_RE, COMMENT_SPAN_RE, CITE_OPT_RE, MACRO_OPT_RE)
        for m in rx.finditer(tex)
    ]
    bridged: list[str] = []

    def _expand_token(token: str) -> list[int]:
        tok = token.strip()
        rm = re.fullmatch(r"(\d+)\s*(?:--|-)\s*(\d+)", tok)
        if rm:
            lo, hi = int(rm.group(1)), int(rm.group(2))
            if lo > hi or (hi - lo) > _MAX_RANGE_EXPAND:
                raise CiteError(
                    f"[{tok}] is an invalid citation range in numeric_map"
                )
            return list(range(lo, hi + 1))
        return [int(tok)]

    def _replace(m: re.Match) -> str:
        if any(s <= m.start() < e for s, e in protected):
            return m.group(0)
        keys: list[str] = []
        for token in m.group(1).split(","):
            for num in _expand_token(token):
                number = str(num)
                if number not in numeric_map:
                    raise CiteError(
                        f"[{number}] has no citekey in numeric_map "
                        f"(missing or out of range; map covers "
                        f"{sorted(numeric_map)})"
                    )
                key = numeric_map[number]
                if key not in keys:
                    keys.append(key)
        cite = "\\cite{" + ",".join(keys) + "}"
        bridged.append(f"{m.group(0)} -> {cite}")
        return cite

    out = NUM_GROUP.sub(_replace, tex)
    for b in bridged:
        print(f"to_cites: bridged numeric citation {b}", file=sys.stderr)
    return out


def _strip_claim_lines(text: str) -> str:
    """Drop whole-line `% @claim:<id>` binding comments (Task 6 convention)."""
    return "".join(
        line for line in text.splitlines(keepends=True)
        if not CLAIM_LINE.match(line)
    )


def _strip_comments(text: str) -> str:
    """Strip unescaped % comments line-by-line for static integrity scans."""
    return "\n".join(COMMENT_SPAN_RE.sub("", line) for line in text.splitlines())


def _find_entry(template_dir: Path) -> str:
    for name in ("main.tex", "template.tex"):
        if (template_dir / name).is_file():
            return name
    raise FileNotFoundError(
        f"no main.tex or template.tex in template dir {template_dir}"
    )


def _strip_pre_maketitle_abstract(text: str) -> str:
    """Remove example abstract blocks occurring before \\maketitle (e.g. ICLR/IEEE)."""
    mk = re.search(r"\\maketitle\b", text)
    if not mk:
        return text
    head = text[: mk.start()]
    tail = text[mk.start() :]
    cleaned_head = re.sub(
        r"\\begin\{abstract\}.*?\\end\{abstract\}\s*",
        "",
        head,
        flags=re.DOTALL,
    )
    return cleaned_head + tail


def _wire(
    entry_text: str,
    inputs: list[str],
    warnings: list[str],
    has_abstract: bool = False,
) -> str:
    """Insert \\input lines: marker path first, else the memo's no-marker rule."""
    if has_abstract:
        entry_text = _strip_pre_maketitle_abstract(entry_text)
    lines = entry_text.splitlines()
    marker_idx = next(
        (i for i, l in enumerate(lines) if MARKER in l), None
    )
    if marker_idx is not None:
        lines[marker_idx + 1:marker_idx + 1] = inputs
        return "\n".join(lines) + "\n"

    maketitle_idx = next(
        (
            i for i, l in enumerate(lines)
            if not l.lstrip().startswith("%") and re.search(r"\\maketitle\b", l)
        ),
        None,
    )
    if maketitle_idx is None:
        begin_idx = next(
            (
                i for i, l in enumerate(lines)
                if not l.lstrip().startswith("%")
                and re.search(r"\\begin\{document\}", l)
            ),
            None,
        )
        if begin_idx is None:
            raise ValueError(
                "no wiring anchor: entry has neither the sections marker, "
                "\\maketitle nor \\begin{document}"
            )
        warnings.append(
            "entry has no \\maketitle; inputs inserted after "
            "\\begin{document} without removing any example body"
        )
        lines[begin_idx + 1:begin_idx + 1] = [""] + inputs
        return "\n".join(lines) + "\n"

    # No-marker path per vendor-notices 四: replace the example body between
    # \maketitle and the bibliography block (bounded upward scan so unrelated `{`
    # lines in non-CVPR example bodies cannot leave example text behind).
    bib_idx = next(
        (
            i for i in range(maketitle_idx + 1, len(lines))
            if not lines[i].lstrip().startswith("%")
            and re.search(r"\\bibliography(?:style)?\{", lines[i])
        ),
        None,
    )
    if bib_idx is None:
        warnings.append(
            "entry has no bibliography command; inputs inserted after "
            "\\maketitle without removing any example body"
        )
        lines[maketitle_idx + 1:maketitle_idx + 1] = [""] + inputs
        return "\n".join(lines) + "\n"

    block_start = bib_idx
    j = bib_idx - 1
    bib_wrapper_re = re.compile(
        r"^\\(?:small|footnotesize|scriptsize|normalsize|bibliographystyle\{[^}]*\})\b"
    )
    bib_open_re = re.compile(
        r"^\{\s*\\(?:small|footnotesize|scriptsize|normalsize)\b"
    )
    while j > maketitle_idx:
        s = lines[j].strip()
        if not s or s.startswith("%"):
            j -= 1
            continue
        if s == "{" or bib_open_re.match(s):
            block_start = j
            break
        if bib_wrapper_re.match(s):
            j -= 1
            continue
        break
    lines[maketitle_idx + 1:block_start] = [""] + inputs + [""]
    return "\n".join(lines) + "\n"


def _integrity(
    entry_text: str,
    bodies: dict[str, str],
    bib_text: str,
    out_dir: Path,
) -> tuple[list[str], list[str], list[str]]:
    """Scan the assembled manuscript for cites/files/raster figures."""
    texts = [_strip_comments(t) for t in (entry_text, *bodies.values())]
    bib_keys = set(BIB_KEY_RE.findall(bib_text))
    missing_citations: set[str] = set()
    missing_files: list[str] = []
    raster_refs: list[str] = []

    def _note_missing(target: str) -> None:
        if target not in missing_files:
            missing_files.append(target)

    for text in texts:
        for m in CITE_RE.finditer(text):
            for key in m.group(1).split(","):
                key = key.strip()
                if key and key not in bib_keys:
                    missing_citations.add(key)
        for m in INPUT_RE.finditer(text):
            target = m.group(1).strip()
            if "\\" in target or "#" in target:
                continue  # macro-driven path, not statically checkable
            if not (
                (out_dir / target).exists()
                or (out_dir / f"{target}.tex").exists()
            ):
                _note_missing(target)
        for m in GRAPHICS_RE.finditer(text):
            target = m.group(1).strip()
            if "\\" in target or "#" in target:
                continue
            ext = Path(target).suffix.lower()
            if ext:
                exists = (out_dir / target).is_file()
                is_raster = ext in RASTER_EXTS
            else:
                resolved = next(
                    (out_dir / f"{target}{e}" for e in GRAPHIC_EXTS
                     if (out_dir / f"{target}{e}").is_file()),
                    None,
                )
                exists = resolved is not None
                is_raster = resolved is not None and (
                    resolved.suffix.lower() in RASTER_EXTS
                )
            if not exists:
                _note_missing(target)
            if is_raster and target not in raster_refs:
                raster_refs.append(target)
    return sorted(missing_citations), missing_files, raster_refs


def _check_compile_logs(
    cwd: str, texfile_name: str, execution_logs: list[dict]
) -> list[str]:
    """Detect fatal TeX errors, undefined cites/refs, and bibtex DB errors."""
    errors: list[str] = []
    for log in execution_logs:
        if "error" in log:
            errors.append(f"{log['cmd']}: {log['error']}")
            continue
        cmd = log.get("cmd", "")
        rc = log.get("returncode", 0)
        if not cmd.startswith("bibtex") and rc != 0:
            errors.append(f"{cmd} exited {rc}")

    tex_log = Path(cwd) / f"{texfile_name}.log"
    if tex_log.is_file():
        ltxt = tex_log.read_text(encoding="utf-8", errors="replace")
        for line in ltxt.splitlines():
            if line.startswith("! "):
                errors.append(line.strip())
                break
        if "Emergency stop" in ltxt:
            errors.append("Emergency stop in TeX log")
        if (
            "There were undefined citations" in ltxt
            or re.search(r"LaTeX Warning: Citation .+ undefined", ltxt)
        ):
            errors.append("undefined citations in TeX log")
        if "There were undefined references" in ltxt:
            errors.append("undefined references in TeX log")

    blg_path = Path(cwd) / f"{texfile_name}.blg"
    bib_blobs: list[str] = []
    if blg_path.is_file():
        bib_blobs.append(blg_path.read_text(encoding="utf-8", errors="replace"))
    for log in execution_logs:
        if log.get("cmd", "").startswith("bibtex"):
            bib_blobs.append((log.get("stdout") or "") + "\n" + (log.get("stderr") or ""))
    blg = "\n".join(bib_blobs)
    if blg:
        for needle in (
            "I couldn't open database file",
            "I found no \\bibdata command",
            "I couldn't open style file",
            "Warning--I didn't find a database entry for",
        ):
            if needle in blg:
                errors.append(f"bibtex: {needle}")
        if re.search(r"\(There (?:was|were) \d+ error messages?\)", blg):
            errors.append("bibtex reported error message(s)")
    return errors


def compile_latex(
    cwd: str,
    texfile_name: str = "template",
    engine: str = "pdflatex",
    timeout: int = 120,
) -> tuple[bool, list[dict]]:
    """Compile in-place; adapted from upstream utils/pdf_utils.py:169-221.

    engine="latexmk" runs a single ``latexmk -pdf`` pass; otherwise the
    ported upstream sequence runs: pdflatex -> bibtex -> pdflatex x2 (with
    the probed engine substituted). Success requires PDF existence, zero TeX
    engine returncode, no timeouts, and clean .log/.blg diagnostics.
    """
    source_pdf = os.path.join(cwd, f"{texfile_name}.pdf")
    if os.path.exists(source_pdf):
        os.remove(source_pdf)

    env = dict(os.environ)
    for var in ["TEXINPUTS", "TEXMFHOME", "TEXMF", "TEXMFVAR", "TEXMFCONFIG"]:
        env.pop(var, None)

    if engine == "latexmk":
        commands = [
            ["latexmk", "-pdf", "-interaction=nonstopmode",
             f"{texfile_name}.tex"],
        ]
    else:
        commands = [
            [engine, "-interaction=nonstopmode", f"{texfile_name}.tex"],
            ["bibtex", texfile_name],
            [engine, "-interaction=nonstopmode", f"{texfile_name}.tex"],
            [engine, "-interaction=nonstopmode", f"{texfile_name}.tex"],
        ]

    execution_logs: list[dict] = []
    for command in commands:
        cmd_str = " ".join(command)
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            execution_logs.append(
                {
                    "cmd": cmd_str,
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
        except subprocess.TimeoutExpired:
            execution_logs.append(
                {"cmd": cmd_str, "error": f"TIMEOUT after {timeout}s"}
            )
        except Exception as e:
            execution_logs.append({"cmd": cmd_str, "error": str(e)})

    log_errors = _check_compile_logs(cwd, texfile_name, execution_logs)
    if log_errors:
        summary = "; ".join(log_errors)
        execution_logs.append({
            "cmd": f"log-check ({summary})",
            "returncode": 1,
            "error": summary,
        })

    success = os.path.exists(source_pdf) and not log_errors
    return success, execution_logs


def _probe_toolchain() -> str | None:
    for name in ("latexmk", "xelatex", "pdflatex"):
        if shutil.which(name):
            return name
    return None


def _ignore_preview_png(src: str, names: list[str]) -> set[str]:
    """Skip companion <stem>.png previews when <stem>.pdf is present."""
    name_set = set(names)
    pdf_stems = {
        Path(n).stem for n in name_set if Path(n).suffix.lower() == ".pdf"
    }
    return {
        n for n in name_set
        if Path(n).suffix.lower() == ".png"
        and Path(n).stem in pdf_stems
        and (Path(src) / n).is_file()
    }


def _has_placeholder(val: str) -> bool:
    s = val.strip()
    return not s or ("<" in s and ">" in s)


def _replace_brace_arg(tex: str, cmd_pattern: str, new_body: str) -> str:
    """Replace the brace-balanced argument of the first uncommented cmd match."""
    for m in re.finditer(cmd_pattern, tex):
        line_start = tex.rfind("\n", 0, m.start()) + 1
        if re.search(r"(?<!\\)%", tex[line_start : m.start()]):
            continue
        open_idx = m.end() - 1
        depth = 0
        i = open_idx
        n = len(tex)
        while i < n:
            ch = tex[i]
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return tex[: open_idx + 1] + new_body + tex[i:]
            i += 1
        break
    return tex


def _apply_outline_metadata(tex: str, outline_path: Path) -> str:
    """Inject title, authors, and paper_id from outline.json when concrete."""
    data = json.loads(outline_path.read_text(encoding="utf-8"))
    title = data.get("title")
    if isinstance(title, str) and not _has_placeholder(title):
        tex = _replace_brace_arg(tex, r"\\title\s*\{", title.strip())

    meta = data.get("metadata") or {}
    if isinstance(meta, dict):
        authors = meta.get("authors")
        if isinstance(authors, list) and authors:
            blocks: list[str] = []
            for a in authors:
                if not isinstance(a, dict):
                    continue
                name = str(a.get("name") or "")
                if _has_placeholder(name):
                    continue
                lines = [name.strip()]
                aff = str(a.get("affiliation") or "")
                if not _has_placeholder(aff):
                    lines.append(aff.strip())
                email = str(a.get("email") or "")
                if not _has_placeholder(email):
                    esc_email = re.sub(r"(?<!\\)_", r"\\_", email.strip())
                    lines.append(f"{{\\tt\\small {esc_email}}}")
                blocks.append("\\\\\n".join(lines))
            if blocks:
                tex = _replace_brace_arg(
                    tex, r"\\author\s*\{", "\n" + "\n\\and\n".join(blocks) + "\n"
                )
        paper_id = meta.get("paper_id")
        if paper_id is not None and not _has_placeholder(str(paper_id)):
            pid = str(paper_id).strip()
            tex = _replace_brace_arg(tex, r"\\def\s*\\paperID\s*\{", pid)
    return tex


def _sync_bibliography(
    wired: str, bib_stem: str, out_dir: Path
) -> str:
    """Rewrite uncommented \\bibliography{...} to bib_stem and prune stale .bib."""
    out_lines: list[str] = []
    bib_cmd_re = re.compile(r"(\\bibliography\{)([^}]*)(\})")
    for line in wired.splitlines(keepends=True):
        code, sep, comment = line.partition("%")
        if not line.lstrip().startswith("%") and bib_cmd_re.search(code):
            def _sub(m: re.Match) -> str:
                old_stems = [s.strip() for s in m.group(2).split(",") if s.strip()]
                if old_stems == [bib_stem]:
                    return m.group(0)
                for old_s in old_stems:
                    if old_s != bib_stem:
                        stale = out_dir / f"{old_s}.bib"
                        if stale.is_file():
                            stale.unlink()
                return f"{m.group(1)}{bib_stem}{m.group(3)}"
            code = bib_cmd_re.sub(_sub, code)
            line = code + sep + comment
        out_lines.append(line)
    return "".join(out_lines)


def compose(
    template_dir,
    sections_dir,
    bib_path,
    figures_dir,
    out_dir,
    numeric_map: dict[str, str] | None = None,
    tables_dir=None,
    outline_path=None,
) -> ComposeReport:
    """Stage the template, wire sections, bridge numeric cites, check, compile.

    out_dir receives: the template files (staged copytree), sections/*.tex
    (claim-marker-stripped, numeric cites converted), optional tables/*.tex,
    figures/* (excluding companion PNG previews), the bib file, the wired
    entry .tex and compose_report.json. compiled is None when no TeX
    toolchain exists (ok is not failed by that).
    """
    template_dir = Path(template_dir)
    sections_dir = Path(sections_dir)
    bib_path = Path(bib_path)
    out_dir = Path(out_dir)
    warnings: list[str] = []

    entry_name = _find_entry(template_dir)
    if not bib_path.is_file():
        raise FileNotFoundError(f"bib file not found: {bib_path}")

    # Staging: ported upstream pattern (methods/paper_writer.py:68, :55).
    shutil.copytree(template_dir, out_dir, dirs_exist_ok=True)
    if figures_dir is not None:
        figures_dir = Path(figures_dir)
        if figures_dir.is_dir():
            shutil.copytree(
                figures_dir,
                out_dir / "figures",
                dirs_exist_ok=True,
                ignore=_ignore_preview_png,
            )
        else:
            warnings.append(f"figures dir not found: {figures_dir}")
    shutil.copy2(bib_path, out_dir / bib_path.name)

    # Sections: filename order, strip Task 6 claim markers, bridge [n] cites.
    section_files = sorted(sections_dir.glob("*.tex"), key=lambda p: p.name)
    if not section_files:
        warnings.append(f"no .tex sections found in {sections_dir}")
    sec_out = out_dir / "sections"
    sec_out.mkdir(exist_ok=True)
    bodies: dict[str, str] = {}
    for path in section_files:
        text = _strip_claim_lines(path.read_text(encoding="utf-8"))
        if numeric_map is not None:
            text = to_cites(text, numeric_map)
        (sec_out / path.name).write_text(text, encoding="utf-8")
        bodies[path.name] = text
    inputs = [f"\\input{{sections/{p.stem}}}" for p in section_files]

    if tables_dir is not None:
        tables_dir = Path(tables_dir)
        if tables_dir.is_dir():
            tab_out = out_dir / "tables"
            tab_out.mkdir(exist_ok=True)
            for path in sorted(tables_dir.glob("*.tex"), key=lambda p: p.name):
                text = _strip_claim_lines(path.read_text(encoding="utf-8"))
                if numeric_map is not None:
                    text = to_cites(text, numeric_map)
                (tab_out / path.name).write_text(text, encoding="utf-8")
                bodies[f"tables/{path.name}"] = text
        else:
            warnings.append(f"tables dir not found: {tables_dir}")

    # R1: several numbers -> one citekey is legal; warn, never error.
    if numeric_map:
        by_key: dict[str, list[str]] = {}
        for number in sorted(
            numeric_map,
            key=lambda s: (0, int(s)) if s.isdigit() else (1, s),
        ):
            by_key.setdefault(numeric_map[number], []).append(number)
        for key, numbers in by_key.items():
            if len(numbers) > 1:
                warnings.append(
                    f"numeric_map: numbers {', '.join(numbers)} all map to "
                    f"citekey '{key}' (multi-point citation; legal)"
                )

    has_abstract = any(
        re.search(r"\\begin\{abstract\}", b) for b in bodies.values()
    )
    entry_path = out_dir / entry_name
    wired = _wire(
        entry_path.read_text(encoding="utf-8"),
        inputs,
        warnings,
        has_abstract=has_abstract,
    )
    if outline_path is not None:
        wired = _apply_outline_metadata(wired, Path(outline_path))
    wired = _sync_bibliography(wired, bib_path.stem, out_dir)
    entry_path.write_text(wired, encoding="utf-8")

    # F4: known cvpr2025 author-kit placeholders surviving in the assembled
    # entry are a WARNING (non-failing): title/author/paperID must come from
    # outline.json before submission (stage-playbook stage-6 checkpoint).
    for marker in CVPR_PLACEHOLDERS:
        if marker in wired:
            warnings.append(
                f"cvpr2025 template placeholder {marker!r} survives in "
                f"{entry_name}; update title/author/paperID from outline.json "
                f"before submission"
            )

    missing_citations, missing_files, raster_refs = _integrity(
        wired, bodies, bib_path.read_text(encoding="utf-8"), out_dir
    )

    tool = _probe_toolchain()
    if tool is None:
        compiled = None
        warnings.append(
            "no LaTeX toolchain found (latexmk/xelatex/pdflatex); "
            "compile skipped"
        )
    else:
        compiled, logs = compile_latex(
            str(out_dir), texfile_name=Path(entry_name).stem, engine=tool
        )
        if not compiled:
            failed = [
                log["cmd"] for log in logs
                if "error" in log or log.get("returncode", 0) != 0
            ]
            warnings.append(
                f"compile with {tool} failed"
                + (f" (commands: {'; '.join(failed)})" if failed else "")
            )

    report = ComposeReport(
        compiled=compiled,
        missing_citations=missing_citations,
        missing_files=missing_files,
        raster_refs=raster_refs,
        warnings=warnings,
    )
    (out_dir / "compose_report.json").write_text(
        json.dumps(
            {
                "compiled": report.compiled,
                "missing_citations": report.missing_citations,
                "missing_files": report.missing_files,
                "raster_refs": report.raster_refs,
                "warnings": report.warnings,
                "ok": report.ok,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Assemble sections + bib + figures into a LaTeX package."
    )
    parser.add_argument("--template", required=True, help="template dir")
    parser.add_argument("--sections", required=True, help="sections dir")
    parser.add_argument("--bib", required=True, help="refs.bib path")
    parser.add_argument("--figures", default=None, help="figures dir")
    parser.add_argument("--tables", default=None, help="optional tables dir")
    parser.add_argument("--outline", default=None, help="optional outline.json for metadata")
    parser.add_argument("--out", required=True, help="output manuscript dir")
    parser.add_argument(
        "--numeric-map", default=None,
        help="JSON file mapping number strings to citekeys",
    )
    args = parser.parse_args(argv)

    numeric_map = None
    if args.numeric_map:
        numeric_map = json.loads(
            Path(args.numeric_map).read_text(encoding="utf-8")
        )
    try:
        report = compose(
            args.template,
            args.sections,
            args.bib,
            args.figures,
            args.out,
            numeric_map=numeric_map,
            tables_dir=args.tables,
            outline_path=args.outline,
        )
    except CiteError as e:
        print(f"cite error: {e}", file=sys.stderr)
        sys.exit(2)
    print(json.dumps({
        "compiled": report.compiled,
        "missing_citations": report.missing_citations,
        "missing_files": report.missing_files,
        "raster_refs": report.raster_refs,
        "warnings": report.warnings,
        "ok": report.ok,
    }, indent=2, ensure_ascii=False))
    sys.exit(0 if report.ok else 1)


if __name__ == "__main__":
    main()