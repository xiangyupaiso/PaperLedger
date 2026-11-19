"""Graded claims ledger audits: grading, numeric provenance, strength mismatch.

Runtime dependencies: stdlib ONLY (argparse/difflib/json/math/os/re/sys/
dataclasses/pathlib). No LLM calls. Python 3.11+.

This is the anti-fabrication backbone of paper-orchestrator. It checks a
claims ledger (JSONL) whose grading semantics align VERBATIM with the
canonical paper-writer references (referenced, not restated):
  - paper-writer/references/evidence-discipline.md  (L0-L4 strength table)
  - paper-writer/references/verification-ladder.md  (Rung 1/2/3; the
    independent citation-verification step is NOT implemented here)

Library surface:
    load_claims(path) -> list[dict]
    audit_claims(claims_path, materials_dir) -> list[str]
    audit_outline(outline_path, claims=None, materials_dir=None) -> list[str]
    audit_numbers(sections_dir, claims, materials_dir,
                  *, bib_path=None, tables_dir=None) -> list[str]
    audit_strength_mismatch(sections_dir, claims,
                            *, tables_dir=None,
                            dispositions_path=None) -> dict   # report-only

Draft -> ledger binding (fixed convention): every claim sentence in
sections/*.tex carries a ``% @claim:<id>[,<id>...]`` comment line above it.
A numeric sentence with NO marker is an orphan violation; a marker pointing
at a nonexistent id is a dead-link violation. A marker above ``\begin{table}``
binds the table caption and tabular rows. latex_compose.py strips these
comment lines at assembly (Task 5); this module only reads them.

Level -> boundary is derived (LEVEL_BOUNDARY); audit_claims flags any
level/boundary contradiction. Numeric provenance: after excluding numbers
that do not participate (non-data display/inline math, cite/ref/graphics/
layout args, TeX counters, parenthesized citation years, hyphenated model
identifiers, small list enumerations), every remaining prose/table number must
appear verbatim (or numerically equal with identical sign) in the origin span
of a bound L1 claim, or match a whitelisted conversion (or declared chain)
on that claim. L2/L3/L0/L4 cannot support specific numbers; retrieval:/
field_common origins have no local line span.

CLI:
    python ledger_audit.py claims.jsonl --materials materials/ \
        [--outline outline.json] \
        [--sections sections/ --tables tables/ --bib refs.bib \
         --strength-report [--dispositions dispositions.json]]
Exit 0 iff audit_claims + audit_outline + audit_numbers violations are zero.
--strength-report prints the mismatch report but does NOT gate the exit code
(no numeric budget/quota anywhere in that report). Fail-closed inputs: a
missing claims/outline/dispositions/bib file, or --sections pointing at a
missing dir / a dir with no .tex files, is an actionable stderr error + exit 1
(never a silent "0 violations").
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# --- grading: level -> derived boundary (semantics per evidence-discipline.md)
LEVEL_BOUNDARY = {
    "L1": "any",
    "L2": "headline_only",
    "L3": "related_work_only",
    "L0": "directional",
    "L4": "none",
}

# --- hedging signal set: EXACTLY these four words. limitations/suggest/
#     indicate are NOT penalty words and appear in no vocabulary constant.
HEDGE_WORDS = ("may", "could", "potentially", "likely")
HEDGE_RE = re.compile(r"\b(?:may|could|potentially|likely)\b", re.IGNORECASE)

# --- numeric conversion whitelist (module constants; documented in
#     references/outline-schema.md). A claim must DECLARE a conversion in its
#     "conversions" list for it to excuse a prose number.
CONVERSIONS = {
    "x100_percent": lambda x: x * 100.0,   # fraction -> percent
    "div100_percent": lambda x: x / 100.0,  # percent -> fraction
    "round_0dp": lambda x: round(x),
    "round_1dp": lambda x: round(x, 1),
    "round_2dp": lambda x: round(x, 2),
    "round_3dp": lambda x: round(x, 3),
}

# --- disposition advice (both directions offered; never a forced direction)
_ADVICE_WEAKENED = (
    "Evidence is L1/L2: upgrade-to-assertive (state the finding directly), "
    "OR fix-ledger/shrink-claim if the uncertainty is real (record it in the "
    "ledger or narrow the claim). Author decides; no forced direction."
)
_ADVICE_OVERCLAIMED = (
    "Support is L3/L4 or absent: fix-ledger/shrink-claim (reduce to "
    "citation-level deixis, obtain stronger evidence, or remove the sentence), "
    "OR upgrade-to-assertive only after the ledger is upgraded to L1/L2. "
    "Author decides; no forced direction."
)

# --- origin / marker / number patterns
MATERIAL_RE = re.compile(r"^material:(.+)#L(\d+)(?:-L(\d+))?$")
MARKER_RE = re.compile(r"^\s*%\s*@claim:\s*(.+?)\s*$")
# a prose data number: optional leading SIGN (direction of effect is meaning),
# not embedded in a word/identifier, optional decimal and exponent, optional
# quantitative unit suffix (20x, 70B, 16GB, 120FPS, 100ms, 18K); a trailing
# sentence period is allowed (0.93.) but 1.2.3 is not.
NUMBER_RE = re.compile(
    r"(?<![\w.])([+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"(?:(?=(?:[xX×]|(?:[KMGT]?B|ms|ns|us|Hz|kHz|MHz|GHz|FPS|fps|px)|[kKMBT])(?!\w))|(?!\w))"
    r"(?!\.\d)"
)

# --- exclusion set: numbers that do NOT participate in numeric provenance
DISPLAY_MATH_RE = re.compile(
    r"\\begin\{(equation|align|gather|multline|flalign|eqnarray)\*?\}.*?\\end\{\1\*?\}",
    re.DOTALL,
)
DISPLAY_DOLLAR_RE = re.compile(r"(?<!\\)\$\$.*?(?<!\\)\$\$", re.DOTALL)
DISPLAY_BRACKET_RE = re.compile(r"\\\[.*?\\\]", re.DOTALL)
INLINE_PAREN_MATH_RE = re.compile(r"\\\(.*?\\\)", re.DOTALL)
# $ delimiters must be unescaped: \$ is a literal dollar sign, not math.
INLINE_MATH_RE = re.compile(r"(?<!\\)\$[^$]*?(?<!\\)\$")
# Inline math carrying empirical data values (percents, multipliers, +/- deltas,
# or error bars) participates in numeric provenance rather than being blanked.
DATA_INLINE_MATH_RE = re.compile(
    r"\\%"
    r"|\d\s*\\times(?![A-Za-z])"
    r"|(?:\d\s*\\pm(?![A-Za-z])|\\pm(?![A-Za-z])\s*[+-]?(?:\d|\.\d))"
    r"|^\s*[+-](?:\d+(?:\.\d+)?|\.\d+)(?:\s*(?:\\%|\\times(?![A-Za-z])|pp|pts?|dB|ms|s|x))?\s*$"
)
INLINE_MATH_TOKENS_RE = re.compile(
    r"\\(?:%|times|pm|approx|sim|le|ge|leq|geq)(?![A-Za-z])"
    r"|\\(?:text(?:bf|it|rm|sf|tt)?|mathbf|mathrm)\{|\}"
)
CITE_CMD_CAPTURE = (
    r"\\(?:cite[a-z]*|parencite|textcite|autocite|footcite)"
    r"\*?(?:\[[^\]]*\])*\{([^}]*)\}"
)
CITE_EXTRACT_RE = re.compile(CITE_CMD_CAPTURE)
CITE_REF_RE = re.compile(
    r"\\(?:cite[a-z]*|parencite|textcite|autocite|footcite)\*?(?:\[[^\]]*\])*\{[^}]*\}"
    r"|\\(?:[Cc]?ref|eqref|autoref|pageref|nameref|label)\*?\{[^}]*\}"
)
GRAPHICS_CMD_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{[^}]*\}")
LAYOUT_CMD_RE = re.compile(
    r"\\(?:vspace|hspace)\*?\{[^}]*\}"
    r"|\\scalebox\{[^}]*\}(?:\[[^\]]*\])?"
    r"|\\resizebox\{[^}]*\}\{[^}]*\}"
    r"|\\begin\{minipage\}(?:\[[^\]]*\])?\{[^}]*\}"
    r"|\\(?:multicolumn|multirow)\{\d+\}\{[^}]*\}"
    r"|\\(?:setlength|addtolength)\{[^}]*\}\{[^}]*\}"
    r"|\\renewcommand\{\\arraystretch\}\{[^}]*\}"
)
COUNTER_RE = re.compile(
    r"\\(?:setcounter|addtocounter|newcounter|stepcounter|refstepcounter)"
    r"\{[^}]*\}(?:\{[^}]*\})?"
    r"|\\(?:value|arabic|roman|Roman|alph|Alph|fnsymbol)\{[^}]*\}"
    r"|\\(?:the|number)\s*\\?[A-Za-z]+"
)
# parenthesized publication years are citation metadata, not data numbers
YEAR_PAREN_RE = re.compile(r"\((?:19|20)\d{2}\)")
IDENT_HYPHEN_NUM_RE = re.compile(
    r"\b[A-Za-z][A-Za-z0-9_]*(?:-[A-Za-z0-9_]*\d[A-Za-z0-9_]*(?:\.\d+)*)+"
)
ENUM_MARKER_RE = re.compile(r"(?<![A-Za-z0-9])\((?:[1-9]|1\d|20)\)(?=\s)")
RANGE_DASH_RE = re.compile(r"(\d+(?:\.\d+)?)[ \t]*(?:--|-|–)[ \t]*(\d+(?:\.\d+)?)")
COMMENT_RE = re.compile(r"(?<!\\)%.*")
STRUCTURAL_RE = re.compile(
    r"^\\(?:section|subsection|subsubsection|paragraph|begin|end|maketitle"
    r"|title|author|input|include|bibliography|bibliographystyle|appendix|label)\b"
)
TABLE_FMT_RE = re.compile(
    r"^\\(?:centering|toprule|midrule|bottomrule|hline|cline\{[^}]*\})\s*$"
)
BIB_KEY_RE = re.compile(r"@\w+\s*\{\s*([^,\s{}]+)\s*,")

# --- sentence segmentation (abbreviation-aware + CJK punctuation)
SENT_END_RE = re.compile(r"(?:[.!?](?=\s|$)|[。！？])")
ABBREV_BEFORE_RE = re.compile(
    r"(?:\b(?:et al|e\.g|i\.e|cf|Fig|Tab|Table|Alg|Eq|Sec|Ref|App|Def|Thm"
    r"|Prop|Lem|Cor|Ch|vs|approx|etc|w\.r\.t|i\.i\.d|s\.t|Dr|Mr|Ms|Prof"
    r"|Inc|Ltd|No|pp|p|Vol))\.$",
    re.IGNORECASE,
)

# --- section classification
METHOD_RE = re.compile(r"method", re.IGNORECASE)
RELATED_WORK_RE = re.compile(
    r"related|prior[\s_-]*work|literature|background", re.IGNORECASE
)
SECTION_TITLE_RE = re.compile(r"\\(?:sub)*section\*?\{([^}]*)\}")
TOP_SECTION_RE = re.compile(r"\\section\*?\{([^}]*)\}")

# --- canonical L3 deixis shape (report-only exemption in the strength audit):
#     supports single author, two authors (and / &), et al., parenthesized year
#     or numeric-style inline \cite right after the author.
DEIXIS_VERBS = (
    "addressed|studied|proposed|investigated|explored|examined"
    "|introduced|presented|developed|analy[sz]ed"
)
_AUTHOR_REF = (
    r"[A-Z][A-Za-z'-]+(?:[\s~]+(?:et[\s~]+al\.|"
    r"(?:and|\\?&|&amp;)[\s~]+[A-Z][A-Za-z'-]+))?"
)
DEIXIS_RE = re.compile(
    r"\b" + _AUTHOR_REF + r"[\s~]*\((?:19|20)\d{2}\)[\s~]*"
    r"(?:" + DEIXIS_VERBS + r")\b"
    r".*?" + CITE_CMD_CAPTURE
)
DEIXIS_CITE_FIRST_RE = re.compile(
    r"\b" + _AUTHOR_REF + r"[\s~]*" + CITE_CMD_CAPTURE + r"[\s~]*"
    r"(?:" + DEIXIS_VERBS + r")\b"
)

# --- field_common proper-noun heuristic (simple, documented; no NLP):
#     capitalized multi-word names, camelCase identifiers, ALL-CAPS acronyms.
PROPER_MULTIWORD_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")
CAMELCASE_RE = re.compile(r"\b[A-Za-z]*[a-z][A-Z][A-Za-z]*\b")
ACRONYM_RE = re.compile(r"\b[A-Z]{2,}\b")


@dataclass
class _Unit:
    """One prose/table unit aligned to its bound claim ids (via @claim markers).

    ``raw`` is the same unit with only comments stripped (math/cite/year
    still visible), used solely by the canonical-deixis exemption; it is ""
    when raw/cleaned sentence segmentation disagrees (exemption then never
    applies -- fail toward flagging).
    """

    file: str
    line: int
    text: str
    bound: list[str]
    raw: str = ""
    section: str = ""
    in_table: bool = False


# --------------------------------------------------------------------- ledger


def load_claims(path: Path | str) -> list[dict]:
    """Read a JSONL ledger; raise ValueError (with line number) on bad rows."""
    rows: list[dict] = []
    text = Path(path).read_text(encoding="utf-8")
    for i, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{i}: invalid JSON in ledger line: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{i}: ledger line must be a JSON object")
        rows.append(row)
    return rows


def _resolve_material(origin: str, materials_dir: Path | str):
    """Return (span_text, problem). span_text is None when the origin is dead."""
    m = MATERIAL_RE.match(origin)
    if not m:
        return None, (
            "malformed material origin "
            "(expected material:<relpath>#L<start>[-L<end>])"
        )
    rel, start_s, end_s = m.groups()
    start = int(start_s)
    end = int(end_s) if end_s else start
    base = Path(materials_dir).resolve()
    path = (base / rel).resolve()
    if path != base and not str(path).startswith(str(base) + os.sep):
        return None, f"origin path escapes materials dir: {rel}"
    if not path.is_file():
        return None, f"origin file not found: {rel}"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"origin file unreadable: {rel} ({exc})"
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    n = len(lines)
    if start < 1 or end < start or end > n:
        rng = f"#L{start_s}" + (f"-L{end_s}" if end_s else "")
        return None, f"dead line range {rng} beyond file length ({n} lines): {rel}"
    return "\n".join(lines[start - 1 : end]), None


def _proper_noun_hits(text: str) -> list[str]:
    hits: list[str] = []
    for rx in (PROPER_MULTIWORD_RE, CAMELCASE_RE, ACRONYM_RE):
        hits.extend(rx.findall(text))
    seen: set[str] = set()
    out: list[str] = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def audit_claims(claims_path: Path | str, materials_dir: Path | str) -> list[str]:
    """Ledger-level violations: missing level, dead origins, level/boundary
    contradictions, L4 rows, field_common with digits/proper nouns, undeclared
    conversions, duplicate ids."""
    try:
        rows = load_claims(claims_path)
    except ValueError as exc:
        return [str(exc)]
    violations: list[str] = []
    seen: set[str] = set()
    for row in rows:
        cid = row.get("id", "<no-id>")
        prefix = f"{cid}: "
        for key in ("id", "claim", "origin", "evidence_level", "boundary"):
            if key not in row:
                violations.append(prefix + f"missing required key '{key}'")
        level = row.get("evidence_level")
        if level is not None and level not in LEVEL_BOUNDARY:
            violations.append(prefix + f"unknown evidence_level '{level}'")
        if level in LEVEL_BOUNDARY:
            expected = LEVEL_BOUNDARY[level]
            if row.get("boundary") != expected:
                violations.append(
                    prefix
                    + f"level/boundary contradiction: {level} derives boundary "
                    f"'{expected}', got '{row.get('boundary')}'"
                )
            if level == "L4":
                violations.append(
                    prefix
                    + "L4 (model memory) supports nothing and never enters the "
                    "ledger; remove the row"
                )
        origin = row.get("origin", "")
        if origin == "field_common":
            claim_text = row.get("claim", "")
            problems = []
            if re.search(r"\d", claim_text):
                problems.append("digits")
            pn = _proper_noun_hits(claim_text)
            if pn:
                problems.append(f"proper-noun-like tokens {pn}")
            if problems:
                violations.append(
                    prefix
                    + "field_common claim violates L0 (no numbers/names): "
                    + "; ".join(problems)
                )
        elif origin.startswith("material:"):
            _, prob = _resolve_material(origin, materials_dir)
            if prob:
                violations.append(prefix + prob)
        elif origin.startswith("retrieval:"):
            if not origin.split(":", 1)[1].strip():
                violations.append(prefix + "retrieval origin has empty citekey")
        elif origin:
            violations.append(prefix + f"unknown origin scheme: {origin}")
        convs = row.get("conversions")
        if convs is not None:
            if not isinstance(convs, list):
                violations.append(prefix + "'conversions' must be a list")
            else:
                for cv in convs:
                    if cv not in CONVERSIONS:
                        violations.append(
                            prefix
                            + f"undeclared conversion '{cv}' not in whitelist "
                            f"{sorted(CONVERSIONS)}"
                        )
        if cid in seen:
            violations.append(prefix + "duplicate claim id")
        seen.add(cid)
    return violations


# ------------------------------------------------------------- text alignment


def _blank_match(m: re.Match) -> str:
    """Replace a region with whitespace, preserving newlines (line numbers)."""
    return "".join("\n" if ch == "\n" else " " for ch in m.group(0))


def _handle_inline_math(m: re.Match) -> str:
    """Keep empirical data math ($93.4\\%$, $1.8\\times$, $+12.4$) for audit;
    blank purely symbolic inline math ($1e^{-3}$, $\\alpha=.57$, $0.5$)."""
    full = m.group(0)
    inner = full[1:-1]
    if not DATA_INLINE_MATH_RE.search(inner):
        return _blank_match(m)
    cleaned_inner = INLINE_MATH_TOKENS_RE.sub(_blank_match, inner)
    return " " + cleaned_inner + " "


def _blank_range_dash(m: re.Match) -> str:
    gap = " " * (m.start(2) - m.end(1))
    return f"{m.group(1)}{gap}{m.group(2)}"


def _exclude_regions(text: str) -> str:
    """Blank out numbers that do not participate in numeric provenance.

    Comments are stripped FIRST (line-preserving): a stray ``$`` inside a
    comment must not pair with a prose math delimiter and swallow the prose
    between them. Math ``$`` delimiters are guarded against escaped ``\\$``.
    """
    text = "\n".join(COMMENT_RE.sub("", line) for line in text.split("\n"))
    for rx in (
        DISPLAY_MATH_RE,
        DISPLAY_DOLLAR_RE,
        DISPLAY_BRACKET_RE,
        INLINE_PAREN_MATH_RE,
    ):
        text = rx.sub(_blank_match, text)
    text = INLINE_MATH_RE.sub(_handle_inline_math, text)
    for rx in (
        CITE_REF_RE,
        GRAPHICS_CMD_RE,
        LAYOUT_CMD_RE,
        COUNTER_RE,
        YEAR_PAREN_RE,
        IDENT_HYPHEN_NUM_RE,
        ENUM_MARKER_RE,
    ):
        text = rx.sub(_blank_match, text)
    text = RANGE_DASH_RE.sub(_blank_range_dash, text)
    return text


def _split_sentences(text: str) -> list[tuple[str, int]]:
    """Split into (sentence, start_offset); abbreviations do not end sentences."""
    result: list[tuple[str, int]] = []
    start = 0
    for m in SENT_END_RE.finditer(text):
        if m.group(0) == "." and ABBREV_BEFORE_RE.search(text[: m.start() + 1]):
            continue
        end = m.end()
        chunk = text[start:end]
        seg = chunk.strip()
        if seg:
            result.append((seg, start + (len(chunk) - len(chunk.lstrip()))))
        start = end
    tail = text[start:]
    seg = tail.strip()
    if seg:
        result.append((seg, start + (len(tail) - len(tail.lstrip()))))
    return result


def _emit_block(
    rel,
    block_lines,
    bound,
    units,
    raw_block_lines=None,
    section="",
    in_table=False,
):
    text = " ".join(t for _, t in block_lines)
    offsets = []
    pos = 0
    for ln, t in block_lines:
        offsets.append((pos, ln))
        pos += len(t) + 1
    sentences = _split_sentences(text)
    raw_sentences: list[tuple[str, int]] = []
    if raw_block_lines:
        raw_text = " ".join(t for _, t in raw_block_lines)
        cand = _split_sentences(raw_text)
        if len(cand) == len(sentences):
            raw_sentences = cand
    for idx, (sent, off) in enumerate(sentences):
        line_no = block_lines[0][0]
        for start, ln in offsets:
            if start <= off:
                line_no = ln
            else:
                break
        raw = raw_sentences[idx][0] if raw_sentences else ""
        unit_bound = bound if (idx == 0 or in_table) else []
        units.append(
            _Unit(
                rel,
                line_no,
                sent,
                list(unit_bound),
                raw,
                section=section,
                in_table=in_table,
            )
        )


def _parse_tex_file(
    path: Path,
    rel: str,
    units: list[_Unit],
    markers: list[tuple[str, int, str]],
    *,
    initial_in_table: bool = False,
) -> None:
    raw = path.read_text(encoding="utf-8")
    cleaned = _exclude_regions(raw)
    raw_lines = raw.split("\n")
    clean_lines = cleaned.split("\n")
    pending: list[str] = []
    block_lines: list[tuple[int, str]] = []
    block_raw: list[tuple[int, str]] = []
    block_bound: list[str] = []
    in_table = initial_in_table
    table_bound: list[str] = []
    current_section = ""

    def close_block():
        nonlocal block_lines, block_raw, block_bound
        if block_lines:
            _emit_block(
                rel,
                block_lines,
                block_bound,
                units,
                block_raw,
                section=current_section,
                in_table=in_table,
            )
            block_lines = []
            block_raw = []
            block_bound = []

    for i, (raw_l, clean_l) in enumerate(zip(raw_lines, clean_lines), 1):
        mm = MARKER_RE.match(raw_l)
        if mm:
            close_block()
            ids = [x.strip() for x in mm.group(1).split(",") if x.strip()]
            pending.extend(ids)
            markers.extend((rel, i, cid) for cid in ids)
            continue
        if raw_l.lstrip().startswith("%"):
            close_block()
            continue

        sec_m = TOP_SECTION_RE.search(COMMENT_RE.sub("", raw_l))
        if sec_m:
            current_section = sec_m.group(1).strip()

        raw_no_comment = COMMENT_RE.sub("", raw_l).strip()
        if re.match(r"^\\begin\{table\*?\}", raw_no_comment):
            close_block()
            in_table = True
            if pending:
                table_bound = list(pending)
                pending = []
            continue
        if re.match(r"^\\end\{table\*?\}", raw_no_comment):
            close_block()
            in_table = initial_in_table
            table_bound = []
            continue
        if initial_in_table and re.match(r"^\\begin\{tabular\*?\}", raw_no_comment):
            close_block()
            if pending and not table_bound:
                table_bound = list(pending)
                pending = []
            continue

        stripped = clean_l.strip()
        if not stripped or STRUCTURAL_RE.match(stripped):
            close_block()
            continue
        if TABLE_FMT_RE.match(stripped) or stripped == r"\\":
            close_block()
            continue

        if not block_lines:
            if pending:
                block_bound = pending
                pending = []
            elif in_table and table_bound:
                block_bound = list(table_bound)
            else:
                block_bound = []
        block_lines.append((i, stripped))
        block_raw.append((i, raw_no_comment))
    close_block()


def _sentence_units(
    sections_dir: Path | str, tables_dir: Path | str | None = None
):
    """Parse sections/*.tex (and optional tables/*.tex) into (units, markers).

    A marker binds the FIRST sentence of the next prose block; a marker
    immediately above ``\\begin{table}`` binds the whole table environment.
    Blank lines, comment lines and structural command lines break blocks.

    ``markers`` records EVERY parsed marker id as (file, line, id), independent
    of whether a prose block consumes it -- so a dangling marker (at EOF, or
    followed only by comments/structural lines) is still validated against the
    ledger (canonical editing-residue case).
    """
    units: list[_Unit] = []
    markers: list[tuple[str, int, str]] = []
    for path in sorted(Path(sections_dir).glob("*.tex")):
        _parse_tex_file(path, path.name, units, markers, initial_in_table=False)
    if tables_dir is not None:
        for path in sorted(Path(tables_dir).glob("*.tex")):
            _parse_tex_file(
                path, f"tables/{path.name}", units, markers, initial_in_table=True
            )
    return units, markers


def _is_methods_section(name: str, text: str) -> bool:
    if METHOD_RE.search(Path(name).stem):
        return True
    return any(METHOD_RE.search(m.group(1)) for m in SECTION_TITLE_RE.finditer(text))


def _is_related_work_unit(u: _Unit, related_files: set[str]) -> bool:
    if u.file.startswith("tables/"):
        return False
    if u.section:
        return bool(RELATED_WORK_RE.search(u.section))
    return u.file in related_files


def _is_related_work_file(name: str, text: str) -> bool:
    if RELATED_WORK_RE.search(Path(name).stem):
        return True
    return any(RELATED_WORK_RE.search(m.group(1)) for m in SECTION_TITLE_RE.finditer(text))


# ------------------------------------------------------------- numeric audit


def _span_text(origin, materials_dir, cache):
    if origin not in cache:
        if origin.startswith("material:"):
            cache[origin] = _resolve_material(origin, materials_dir)[0]
        else:
            cache[origin] = None  # retrieval:/field_common have no line span
    return cache[origin]


def _same_sign(a: float, b: float) -> bool:
    if a == 0.0 and b == 0.0:
        return True
    return (a < 0) == (b < 0)


def _number_supported(n, valid, materials_dir, cache) -> bool:
    try:
        val = float(n)
    except ValueError:
        val = None
    for c in valid:
        if c.get("evidence_level") != "L1":
            continue  # only L1 full text/data can support specific numbers
        span = _span_text(c.get("origin", ""), materials_dir, cache)
        if span is None:
            continue
        span_nums = NUMBER_RE.findall(span)
        # verbatim, sign-aware: a leading '+' is cosmetic, but '-' is meaning
        # (direction of effect), so -0.5 is NOT supported by a span of 0.5.
        if n.lstrip("+") in {s.lstrip("+") for s in span_nums}:
            return True
        if val is not None:
            convs = c.get("conversions") or []
            for s in span_nums:
                try:
                    sv = float(s)
                except ValueError:
                    continue
                if _same_sign(sv, val) and math.isclose(
                    sv, val, rel_tol=0.0, abs_tol=1e-12
                ):
                    return True
                cur = sv
                for conv in convs:
                    fn = CONVERSIONS.get(conv)
                    if fn is None:
                        continue
                    single = fn(sv)
                    if _same_sign(single, val) and math.isclose(
                        single, val, rel_tol=1e-9, abs_tol=1e-9
                    ):
                        return True
                    cur = fn(cur)
                    if _same_sign(cur, val) and math.isclose(
                        cur, val, rel_tol=1e-9, abs_tol=1e-9
                    ):
                        return True
    return False


def _collect_ledger_citekeys(claims: list[dict]) -> dict[str, set[str]]:
    by_key: dict[str, set[str]] = {}
    for c in claims:
        if not isinstance(c, dict):
            continue
        lvl = c.get("evidence_level", "")
        origin = c.get("origin", "")
        if origin.startswith("retrieval:"):
            k = origin.split(":", 1)[1].strip()
            if k:
                by_key.setdefault(k, set()).add(lvl)
        ck = c.get("citekey")
        if isinstance(ck, str) and ck.strip():
            by_key.setdefault(ck.strip(), set()).add(lvl)
    return by_key


def _audit_bib_citations(
    sections_dir: Path | str,
    tables_dir: Path | str | None,
    claims: list[dict],
    bib_path: Path | str,
    already_flagged_l3: set[tuple[str, int]] | None = None,
) -> list[str]:
    violations: list[str] = []
    flagged = already_flagged_l3 or set()
    bib_keys = set(
        BIB_KEY_RE.findall(Path(bib_path).read_text(encoding="utf-8"))
    )
    ledger_keys = _collect_ledger_citekeys(claims)
    tex_files = [(p.name, p) for p in sorted(Path(sections_dir).glob("*.tex"))]
    if tables_dir is not None:
        tex_files.extend(
            (f"tables/{p.name}", p)
            for p in sorted(Path(tables_dir).glob("*.tex"))
        )
    for rel, path in tex_files:
        raw = path.read_text(encoding="utf-8")
        no_comments = "\n".join(COMMENT_RE.sub("", l) for l in raw.split("\n"))
        file_is_related = _is_related_work_file(rel, no_comments)
        current_sec = ""
        for i, line in enumerate(no_comments.split("\n"), 1):
            sm = TOP_SECTION_RE.search(line)
            if sm:
                current_sec = sm.group(1).strip()
            in_related = (
                bool(RELATED_WORK_RE.search(current_sec))
                if current_sec
                else file_is_related
            )
            for m in CITE_EXTRACT_RE.finditer(line):
                for key in m.group(1).split(","):
                    key = key.strip()
                    if not key:
                        continue
                    if key not in bib_keys:
                        violations.append(
                            f"{rel}:{i}: citation key '{key}' not found in {Path(bib_path).name}"
                        )
                    if key not in ledger_keys:
                        violations.append(
                            f"{rel}:{i}: unledgered citation '{key}' has no row in claims ledger"
                        )
                    elif (
                        not in_related
                        and ledger_keys[key] == {"L3"}
                        and (rel, i) not in flagged
                    ):
                        violations.append(
                            f"{rel}:{i}: L3-only citation '{key}' used in non-related-work "
                            f"section ({rel}) - boundary related_work_only"
                        )
    return violations


def audit_numbers(
    sections_dir: Path | str,
    claims: list[dict],
    materials_dir: Path | str,
    *,
    bib_path: Path | str | None = None,
    tables_dir: Path | str | None = None,
) -> list[str]:
    """Numeric provenance + binding + boundary violations (gate CLI exit code)."""
    violations: list[str] = []
    flagged_l3: set[tuple[str, int]] = set()
    by_id = {c.get("id"): c for c in claims if isinstance(c, dict)}
    units, markers = _sentence_units(sections_dir, tables_dir=tables_dir)
    # Dead-link check is UNCONDITIONAL: every parsed marker id is validated
    # against the ledger, even a dangling marker no prose sentence consumes.
    for file, line, cid in markers:
        if cid not in by_id:
            violations.append(
                f"{file}:{line}: dead-link @claim marker -> nonexistent id '{cid}'"
            )
    files = {
        p.name: p.read_text(encoding="utf-8")
        for p in sorted(Path(sections_dir).glob("*.tex"))
    }
    methods = {name for name, txt in files.items() if _is_methods_section(name, txt)}
    related_files = {
        name for name, txt in files.items() if _is_related_work_file(name, txt)
    }
    cache: dict[str, str | None] = {}
    for u in units:
        valid = [by_id[i] for i in u.bound if i in by_id]
        in_related = _is_related_work_unit(u, related_files)
        if not in_related:
            for c in valid:
                if c.get("evidence_level") == "L3" or c.get("boundary") == "related_work_only":
                    flagged_l3.add((u.file, u.line))
                    origin = c.get("origin", "")
                    loc = (
                        origin.split(":", 1)[1]
                        if origin.startswith("retrieval:")
                        else origin
                    )
                    if u.file in methods or (u.section and METHOD_RE.search(u.section)):
                        violations.append(
                            f"{u.file}:{u.line}: L3 metadata claim '{c.get('id')}' "
                            f"({loc}) bound in methods section - metadata-only evidence "
                            f"cannot support method detail (boundary related_work_only)"
                        )
                    else:
                        violations.append(
                            f"{u.file}:{u.line}: L3 metadata claim '{c.get('id')}' "
                            f"({loc}) bound in non-related-work section ({u.file}) - "
                            f"metadata-only evidence is limited to related work "
                            f"(boundary related_work_only)"
                        )
        if valid and all(
            c.get("evidence_level") == "L0" or c.get("origin") == "field_common"
            for c in valid
        ):
            pn = _proper_noun_hits(u.text)
            if pn:
                violations.append(
                    f"{u.file}:{u.line}: L0 (field_common) prose contains "
                    f"proper-noun-like tokens {pn}"
                )
        nums = NUMBER_RE.findall(u.text)
        if not nums:
            continue
        if not u.bound:
            violations.append(
                f"{u.file}:{u.line}: orphan numeric sentence (no @claim marker): "
                + ", ".join(nums)
            )
            continue
        if not valid:
            continue  # dead-link already reported; nothing to verify against
        for n in nums:
            if _number_supported(n, valid, materials_dir, cache):
                continue
            l1 = [c for c in valid if c.get("evidence_level") == "L1"]
            if not l1:
                lv = "/".join(sorted({c.get("evidence_level", "?") for c in valid}))
                violations.append(
                    f"{u.file}:{u.line}: number '{n}' bound only to {lv} claim(s) "
                    f"{[c.get('id') for c in valid]} - level cannot support specific "
                    f"numbers (need L1 full text/data)"
                )
            else:
                violations.append(
                    f"{u.file}:{u.line}: number '{n}' not found in origin span of "
                    f"bound L1 claim(s) {[c.get('id') for c in l1]} (no verbatim "
                    f"match, no declared whitelisted conversion)"
                )
    if bib_path is not None:
        violations.extend(
            _audit_bib_citations(
                sections_dir,
                tables_dir,
                claims,
                bib_path,
                already_flagged_l3=flagged_l3,
            )
        )
    return violations


# ------------------------------------------------------ strength mismatch audit


def _best_match(text, valid):
    if not valid:
        return None, 0.0
    tl = text.lower()
    best_id, best_ratio = None, -1.0
    for c in valid:
        r = difflib.SequenceMatcher(None, c.get("claim", "").lower(), tl).ratio()
        if r > best_ratio:
            best_ratio, best_id = r, c.get("id")
    return best_id, best_ratio


def _bound_claim_citekeys(valid: list[dict]) -> set[str]:
    keys: set[str] = set()
    for c in valid:
        origin = c.get("origin", "")
        if origin.startswith("retrieval:"):
            k = origin.split(":", 1)[1].strip()
            if k:
                keys.add(k)
        ck = c.get("citekey")
        if isinstance(ck, str) and ck.strip():
            keys.add(ck.strip())
    return keys


def _canonical_l3_deixis(
    u: _Unit, valid: list[dict], related_files: set[str]
) -> bool:
    """True iff the sentence is EXACTLY the canonical citation-level deixis
    that L3/related_work_only evidence supports (narrow exemption, report-only):
    bound to L3/related_work_only claim(s) in related work + deixis shape
    + matching citekey + no data numbers beyond year/cite."""
    if not valid or not _is_related_work_unit(u, related_files) or not u.raw:
        return False
    if not all(
        c.get("evidence_level") == "L3" or c.get("boundary") == "related_work_only"
        for c in valid
    ):
        return False
    m = DEIXIS_RE.search(u.raw) or DEIXIS_CITE_FIRST_RE.search(u.raw)
    if not m:
        return False
    cited = {k.strip() for k in m.group(1).split(",") if k.strip()}
    bound_keys = _bound_claim_citekeys(valid)
    if bound_keys and cited and not (cited & bound_keys):
        return False
    # u.text has math/cite/ref args/years blanked: any number left is data.
    return not NUMBER_RE.search(u.text)


def _is_structural_signpost(raw: str, text: str) -> bool:
    """True only for non-numeric section/figure structural signposts."""
    if NUMBER_RE.search(text):
        return False
    src = raw or text
    patterns = (
        r"^\s*In this (?:section|subsection|paper|work|chapter),?\s+we\s+"
        r"(?:describe|present|introduce|outline|detail|review|summarize|discuss|provide)\b",
        r"^\s*(?:The\s+(?:remainder|rest)\s+of\s+this\s+(?:paper|work|section)"
        r"|We\s+organize\s+the\s+(?:remainder|rest)\s+of\s+this\s+(?:paper|work))\b",
        r"^\s*(?:Section|Sec\.)[\s~]*(?:\\(?:[Cc]?ref|autoref)\{[^}]*\}|\d+)?\s*"
        r"(?:presents|describes|introduces|discusses|reviews|summarizes|outlines|details)\b",
        r"^\s*(?:Figure|Fig\.|Table|Tab\.|Algorithm|Alg\.)[\s~]*"
        r"\\(?:[Cc]?ref|autoref)\{[^}]*\}\s*"
        r"(?:illustrates|depicts|presents|lists|summarizes|gives|outlines|shows)\b",
    )
    return any(re.search(pat, src, re.IGNORECASE) for pat in patterns)


def _mismatch_fingerprint(
    kind: str, file: str, claim_ids: list[str], sentence: str
) -> str:
    norm = " ".join(sentence.split())
    payload = json.dumps([kind, file, list(claim_ids), norm], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _load_dispositions(path: Path | str) -> set[str]:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        items = data.get("dispositions")
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError(f"{p}: dispositions JSON must be a list or {{'dispositions': [...]}}")
    if not isinstance(items, list):
        raise ValueError(f"{p}: 'dispositions' must be a list")
    accepted: set[str] = set()
    for idx, entry in enumerate(items, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"{p}: disposition #{idx} must be a JSON object")
        fp = entry.get("fingerprint")
        dec = entry.get("decision")
        rat = entry.get("rationale")
        if (
            isinstance(fp, str) and fp.strip()
            and isinstance(dec, str) and dec.strip()
            and isinstance(rat, str) and rat.strip()
        ):
            accepted.add(fp.strip())
    return accepted


def audit_outline(
    outline_path: Path | str,
    claims: list[dict] | None = None,
    materials_dir: Path | str | None = None,
) -> list[str]:
    """Validate outline.json structure, claim links, viz_plan refs, and metadata."""
    p = Path(outline_path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"outline: failed to read/parse {p}: {exc}"]
    if not isinstance(data, dict):
        return ["outline: top-level JSON value must be an object"]

    violations: list[str] = []
    for key in ("title", "venue", "sections", "lit_strategy", "viz_plan"):
        if key not in data:
            violations.append(f"outline: missing required key '{key}'")
    for str_key in ("title", "venue"):
        if str_key in data and (
            not isinstance(data[str_key], str) or not data[str_key].strip()
        ):
            violations.append(f"outline: '{str_key}' must be a non-empty string")

    claim_ids = (
        {c.get("id") for c in claims if isinstance(c, dict) and c.get("id")}
        if claims is not None
        else None
    )

    section_ids: set[str] = set()
    sections = data.get("sections")
    if "sections" in data:
        if not isinstance(sections, list) or not sections:
            violations.append("outline: 'sections' must be a non-empty list")
        else:
            for idx, sec in enumerate(sections):
                if not isinstance(sec, dict):
                    violations.append(f"outline: sections[{idx}] must be an object")
                    continue
                sid = sec.get("id")
                for req in ("id", "kind", "purpose"):
                    val = sec.get(req)
                    if not isinstance(val, str) or not val.strip():
                        violations.append(
                            f"outline: sections[{idx}] missing non-empty '{req}'"
                        )
                if isinstance(sid, str) and sid.strip():
                    if sid in section_ids:
                        violations.append(f"outline: duplicate section id '{sid}'")
                    section_ids.add(sid)
                sec_claims = sec.get("claims")
                if not isinstance(sec_claims, list):
                    violations.append(
                        f"outline: sections[{idx}] ({sid or '?'}) 'claims' must be a list"
                    )
                elif claim_ids is not None:
                    for cid in sec_claims:
                        if cid not in claim_ids:
                            violations.append(
                                f"outline: sections[{idx}] ({sid or '?'}) references "
                                f"nonexistent claim id '{cid}'"
                            )

    ls = data.get("lit_strategy")
    if "lit_strategy" in data:
        if not isinstance(ls, dict):
            violations.append("outline: 'lit_strategy' must be an object")
        else:
            qs = ls.get("queries")
            if (
                not isinstance(qs, list)
                or not qs
                or not all(isinstance(q, str) and q.strip() for q in qs)
            ):
                violations.append(
                    "outline: 'lit_strategy.queries' must be a non-empty list of strings"
                )
            mc = ls.get("must_contain")
            if not isinstance(mc, list) or not all(isinstance(x, str) for x in mc):
                violations.append("outline: 'lit_strategy.must_contain' must be a list of strings")

    vp = data.get("viz_plan")
    if "viz_plan" in data:
        if not isinstance(vp, dict):
            violations.append("outline: 'viz_plan' must be an object")
        else:
            figs = vp.get("figures")
            if not isinstance(figs, list):
                violations.append("outline: 'viz_plan.figures' must be a list")
            else:
                mat_base = Path(materials_dir).resolve() if materials_dir is not None else None
                for idx, fig in enumerate(figs):
                    if not isinstance(fig, dict):
                        violations.append(f"outline: viz_plan.figures[{idx}] must be an object")
                        continue
                    fid = fig.get("id") or f"#{idx}"
                    for req in ("id", "source_section", "kind", "data_ref"):
                        val = fig.get(req)
                        if not isinstance(val, str) or not val.strip():
                            violations.append(
                                f"outline: viz_plan.figures[{idx}] ({fid}) missing non-empty '{req}'"
                            )
                    ss = fig.get("source_section")
                    if isinstance(ss, str) and ss.strip() and section_ids and ss not in section_ids:
                        violations.append(
                            f"outline: viz_plan.figures[{idx}] ({fid}) source_section "
                            f"'{ss}' not found in sections"
                        )
                    dref = fig.get("data_ref")
                    if mat_base is not None and isinstance(dref, str):
                        ref = dref.strip()
                        if ref and not ("<" in ref and ">" in ref):
                            rel_ref = ref[len("materials/"):] if ref.startswith("materials/") else ref
                            cand = (mat_base / rel_ref).resolve()
                            if cand != mat_base and not str(cand).startswith(str(mat_base) + os.sep):
                                violations.append(
                                    f"outline: viz_plan.figures[{idx}] ({fid}) data_ref escapes materials dir: {ref}"
                                )
                            elif not cand.exists():
                                violations.append(
                                    f"outline: viz_plan.figures[{idx}] ({fid}) data_ref not found: {ref}"
                                )

    if "metadata" in data and data["metadata"] is not None:
        meta = data["metadata"]
        if not isinstance(meta, dict):
            violations.append("outline: optional 'metadata' must be an object")
        elif "authors" in meta and meta["authors"] is not None:
            authors = meta["authors"]
            if not isinstance(authors, list) or not all(
                isinstance(a, dict) and isinstance(a.get("name"), str) and a["name"].strip()
                for a in authors
            ):
                violations.append(
                    "outline: 'metadata.authors' must be a list of objects with non-empty 'name'"
                )
    return violations


def audit_strength_mismatch(
    sections_dir: Path | str,
    claims: list[dict],
    *,
    tables_dir: Path | str | None = None,
    dispositions_path: Path | str | None = None,
) -> dict:
    """Report-only strength mismatches. NO numeric budget/quota/gate anywhere.

    weakened_strong: L1/L2-backed sentence hedged with may/could/potentially/likely.
    overclaimed_weak: categorical sentence (none of the four hedge words) whose
    only support is L3/L4, or which has no ledger backing at all. Canonical
    L3 deixis in related work, L0 field_common sentences, tabular data rows,
    and non-numeric structural signposts are excluded from overclaimed_weak noise.
    Each item carries a deterministic fingerprint and disposition advice
    offering BOTH directions.
    """
    disposed_set: set[str] = set()
    disposed_hits: list[str] = []
    if dispositions_path is not None:
        disposed_set = _load_dispositions(dispositions_path)

    by_id = {c.get("id"): c for c in claims if isinstance(c, dict)}
    weakened: list[dict] = []
    overclaimed: list[dict] = []
    units, _markers = _sentence_units(sections_dir, tables_dir=tables_dir)
    files = {
        p.name: p.read_text(encoding="utf-8")
        for p in sorted(Path(sections_dir).glob("*.tex"))
    }
    related_files = {
        name for name, txt in files.items() if _is_related_work_file(name, txt)
    }
    for u in units:
        if u.in_table and ("&" in u.raw or "&" in u.text):
            continue  # tabular cell rows are checked by audit_numbers, not prose voice
        valid = [by_id[i] for i in u.bound if i in by_id]
        hedges = sorted({w.lower() for w in HEDGE_RE.findall(u.text)})
        matched_id, ratio = _best_match(u.text, valid)
        strong = {c.get("evidence_level") for c in valid} & {"L1", "L2"}
        base = {
            "file": u.file,
            "line": u.line,
            "claim_ids": list(u.bound),
            "matched_claim": matched_id,
            "match_ratio": round(ratio, 3),
            "sentence": u.text,
        }
        if hedges and strong:
            fp = _mismatch_fingerprint("weakened_strong", u.file, list(u.bound), u.text)
            if fp in disposed_set:
                disposed_hits.append(fp)
            else:
                weakened.append({
                    **base,
                    "fingerprint": fp,
                    "hedge_words": hedges,
                    "advice": _ADVICE_WEAKENED,
                })
        elif not hedges and not strong:
            if valid and all(
                c.get("evidence_level") == "L0" or c.get("origin") == "field_common"
                for c in valid
            ):
                continue
            if not valid and _is_structural_signpost(u.raw, u.text):
                continue
            if _canonical_l3_deixis(u, valid, related_files):
                continue
            fp = _mismatch_fingerprint("overclaimed_weak", u.file, list(u.bound), u.text)
            if fp in disposed_set:
                disposed_hits.append(fp)
            else:
                overclaimed.append({
                    **base,
                    "fingerprint": fp,
                    "advice": _ADVICE_OVERCLAIMED,
                })
    out: dict = {"weakened_strong": weakened, "overclaimed_weak": overclaimed}
    if dispositions_path is not None:
        out["disposed_fingerprints"] = disposed_hits
    return out


# ------------------------------------------------------------------------ CLI


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Audit a graded claims ledger (grading + outline + numeric "
        "provenance + optional report-only strength mismatch)."
    )
    p.add_argument("claims", type=Path, help="claims.jsonl ledger path")
    p.add_argument("--materials", type=Path, required=True, help="materials dir")
    p.add_argument("--outline", type=Path, help="optional outline.json to validate")
    p.add_argument("--sections", type=Path, help="sections dir with *.tex drafts")
    p.add_argument("--tables", type=Path, help="optional tables dir with *.tex tables")
    p.add_argument("--bib", type=Path, help="optional refs.bib for citation cross-check")
    p.add_argument(
        "--strength-report",
        action="store_true",
        help="print strength-mismatch report (report-only, non-gating; needs --sections)",
    )
    p.add_argument(
        "--dispositions",
        type=Path,
        help="optional dispositions.json suppressing resolved mismatches (needs --strength-report)",
    )
    args = p.parse_args(argv)
    if args.strength_report and args.sections is None:
        p.error("--strength-report requires --sections")
    if args.dispositions is not None and not args.strength_report:
        p.error("--dispositions requires --strength-report")
    if (args.tables is not None or args.bib is not None) and args.sections is None:
        p.error("--tables and --bib require --sections")
    # Fail-closed input gates: a missing ledger or a missing/empty sections
    # dir must NEVER read as "0 violations" (Path.glob on a missing dir
    # yields nothing, which would silently pass the anti-fabrication gate).
    if not args.claims.is_file():
        print(
            f"ERROR: claims ledger not found: {args.claims} -- pass the "
            f"claims.jsonl path (stage-1 output); nothing was audited.",
            file=sys.stderr,
        )
        return 1
    if args.outline is not None and not args.outline.is_file():
        print(
            f"ERROR: --outline file not found: {args.outline}.",
            file=sys.stderr,
        )
        return 1
    if args.sections is not None:
        if not args.sections.is_dir():
            print(
                f"ERROR: --sections dir does not exist: {args.sections} -- "
                f"pass the directory holding sections/*.tex drafts; "
                f"nothing was audited (refusing to report 0 violations).",
                file=sys.stderr,
            )
            return 1
        if not any(args.sections.glob("*.tex")):
            print(
                f"ERROR: --sections dir contains no .tex files: "
                f"{args.sections} -- expected sections/*.tex drafts; "
                f"nothing was audited (refusing to report 0 violations).",
                file=sys.stderr,
            )
            return 1
    if args.tables is not None:
        if not args.tables.is_dir():
            print(
                f"ERROR: --tables dir does not exist: {args.tables} -- "
                f"pass the directory holding tables/*.tex files.",
                file=sys.stderr,
            )
            return 1
        if not any(args.tables.glob("*.tex")):
            print(
                f"ERROR: --tables dir contains no .tex files: {args.tables}.",
                file=sys.stderr,
            )
            return 1
    if args.bib is not None and not args.bib.is_file():
        print(
            f"ERROR: --bib file not found: {args.bib}.",
            file=sys.stderr,
        )
        return 1
    if args.dispositions is not None:
        if not args.dispositions.is_file():
            print(
                f"ERROR: --dispositions file not found: {args.dispositions}.",
                file=sys.stderr,
            )
            return 1
        try:
            _load_dispositions(args.dispositions)
        except (OSError, ValueError) as exc:
            print(f"ERROR: invalid --dispositions file: {exc}", file=sys.stderr)
            return 1

    violations = audit_claims(args.claims, args.materials)
    loaded_claims: list[dict] | None = None
    try:
        loaded_claims = load_claims(args.claims)
    except ValueError:
        loaded_claims = None
    if args.outline is not None:
        violations = violations + audit_outline(
            args.outline, claims=loaded_claims, materials_dir=args.materials
        )
    claims: list[dict] = loaded_claims or []
    if args.sections is not None:
        violations = violations + audit_numbers(
            args.sections,
            claims,
            args.materials,
            bib_path=args.bib,
            tables_dir=args.tables,
        )
    for v in violations:
        print("VIOLATION: " + v)
    if args.strength_report:
        report = audit_strength_mismatch(
            args.sections,
            claims,
            tables_dir=args.tables,
            dispositions_path=args.dispositions,
        )
        print("STRENGTH MISMATCH REPORT (report-only, non-gating):")
        print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"{len(violations)} violation(s)")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())