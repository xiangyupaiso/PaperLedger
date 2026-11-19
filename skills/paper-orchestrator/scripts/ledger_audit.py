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
    audit_numbers(sections_dir, claims, materials_dir) -> list[str]
    audit_strength_mismatch(sections_dir, claims) -> dict   # report-only

Draft -> ledger binding (fixed convention): every claim sentence in
sections/*.tex carries a ``% @claim:<id>[,<id>...]`` comment line above it.
A numeric sentence with NO marker is an orphan violation; a marker pointing
at a nonexistent id is a dead-link violation. latex_compose.py strips these
comment lines at assembly (Task 5); this module only reads them.

Level -> boundary is derived (LEVEL_BOUNDARY); audit_claims flags any
level/boundary contradiction. Numeric provenance: after excluding numbers
that do not participate (cite/ref args, display/inline math, TeX counters,
parenthesized citation years), every remaining prose number must appear
verbatim in the origin span of a bound L1 claim, or match a whitelisted
conversion DECLARED on that claim. L2/L3/L0/L4 cannot support specific
numbers; retrieval:/field_common origins have no local line span.

CLI:
    python ledger_audit.py claims.jsonl --materials materials/ \
        [--sections sections/ --strength-report]
Exit 0 iff audit_claims + audit_numbers violations are zero. --strength-report
prints the mismatch report but does NOT gate the exit code (no numeric
budget/quota anywhere in that report). Fail-closed inputs: a missing claims
file, or --sections pointing at a missing dir / a dir with no .tex files,
is an actionable stderr error + exit 1 (never a silent "0 violations").
"""
from __future__ import annotations

import argparse
import difflib
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
    "round_1dp": lambda x: round(x, 1),
    "round_2dp": lambda x: round(x, 2),
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
# not embedded in a word/identifier, optional decimal and exponent; a trailing
# sentence period is allowed (0.93.) but 1.2.3 is not. Leading-decimal forms
# (.57, -.05) are data numbers too; the (?<![\w.]) guard keeps them from
# matching inside words or version-like chains (0.57 / 1.2.3 stay excluded
# as fragments), and excluded regions are blanked BEFORE this ever runs.
NUMBER_RE = re.compile(
    r"(?<![\w.])([+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?)(?!\w)(?!\.\d)"
)

# --- exclusion set: numbers that do NOT participate in numeric provenance
DISPLAY_MATH_RE = re.compile(
    r"\\begin\{(equation|align|gather)\*?\}.*?\\end\{\1\*?\}", re.DOTALL
)
DISPLAY_DOLLAR_RE = re.compile(r"(?<!\\)\$\$.*?(?<!\\)\$\$", re.DOTALL)
# $ delimiters must be unescaped: \$ is a literal dollar sign, not math.
INLINE_MATH_RE = re.compile(r"(?<!\\)\$[^$]*?(?<!\\)\$")
CITE_REF_RE = re.compile(
    r"\\cite[tp]?\*?(?:\[[^\]]*\])*\{[^}]*\}"
    r"|\\(?:ref|eqref|label)\*?\{[^}]*\}"
)
COUNTER_RE = re.compile(
    r"\\(?:setcounter|addtocounter|newcounter|stepcounter|refstepcounter)"
    r"\{[^}]*\}(?:\{[^}]*\})?"
    r"|\\(?:value|arabic|roman|Roman|alph|Alph|fnsymbol)\{[^}]*\}"
    r"|\\(?:the|number)\s*\\?[A-Za-z]+"
)
# parenthesized publication years are citation metadata, not data numbers
# (the canonical L3 deixis form is "X et al. (Year) addressed Y").
YEAR_PAREN_RE = re.compile(r"\((?:19|20)\d{2}\)")
COMMENT_RE = re.compile(r"(?<!\\)%.*")
STRUCTURAL_RE = re.compile(
    r"^\\(?:section|subsection|subsubsection|paragraph|begin|end|maketitle"
    r"|title|author|input|include|bibliography|bibliographystyle|appendix|label)\b"
)

# --- sentence segmentation (abbreviation-aware)
SENT_END_RE = re.compile(r"[.!?](?=\s|$)")
ABBREV_BEFORE_RE = re.compile(
    r"(?:\b(?:et al|e\.g|i\.e|cf|Fig|Eq|Sec|Ref|vs|approx|Dr|Mr|Ms|Prof"
    r"|Inc|Ltd|No|pp|p|Vol))\.$",
    re.IGNORECASE,
)

# --- methods-section heuristic (filename stem or \section title contains
#     "method", covering method/methods/methodology)
METHOD_RE = re.compile(r"method", re.IGNORECASE)
SECTION_TITLE_RE = re.compile(r"\\(?:sub)*section\*?\{([^}]*)\}")

# --- canonical L3 deixis shape (report-only exemption in the strength audit):
#     "X et al. (Year) addressed/studied/proposed-class Y \cite{...}" is exactly
#     citation-level deixis, which related_work_only evidence SUPPORTS. Narrow
#     on purpose: author token + et al. + parenthesized year + deixis verb +
#     \cite, no data numbers beyond year/cite, never in a methods section.
DEIXIS_VERBS = (
    "addressed|studied|proposed|investigated|explored|examined"
    "|introduced|presented|developed|analy[sz]ed"
)
DEIXIS_RE = re.compile(
    r"\b[A-Z][A-Za-z'-]+[\s~]+et[\s~]+al\.[\s~]*\((?:19|20)\d{2}\)[\s~]*"
    r"(?:" + DEIXIS_VERBS + r")\b"
    r".*?\\cite[tp]?\*?(?:\[[^\]]*\])*\{[^}]*\}"
)

# --- field_common proper-noun heuristic (simple, documented; no NLP):
#     capitalized multi-word names, camelCase identifiers, ALL-CAPS acronyms.
PROPER_MULTIWORD_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")
CAMELCASE_RE = re.compile(r"\b[A-Za-z]*[a-z][A-Z][A-Za-z]*\b")
ACRONYM_RE = re.compile(r"\b[A-Z]{2,}\b")


@dataclass
class _Unit:
    """One prose sentence aligned to its bound claim ids (via @claim markers).

    ``raw`` is the same sentence with only comments stripped (math/cite/year
    still visible), used solely by the canonical-deixis exemption; it is ""
    when raw/cleaned sentence segmentation disagrees (exemption then never
    applies -- fail toward flagging).
    """

    file: str
    line: int
    text: str
    bound: list[str]
    raw: str = ""


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
        INLINE_MATH_RE,
        CITE_REF_RE,
        COUNTER_RE,
        YEAR_PAREN_RE,
    ):
        text = rx.sub(_blank_match, text)
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


def _emit_block(rel, block_lines, bound, units, raw_block_lines=None):
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
        units.append(_Unit(rel, line_no, sent, bound if idx == 0 else [], raw))


def _sentence_units(sections_dir: Path | str):
    """Parse sections/*.tex into (sentence_units, markers).

    A marker binds the FIRST sentence of the next prose block; later sentences
    in the same block are unbound unless they carry their own marker. Blank
    lines, comment lines and structural command lines break blocks.

    ``markers`` records EVERY parsed marker id as (file, line, id), independent
    of whether a prose block consumes it -- so a dangling marker (at EOF, or
    followed only by comments/structural lines) is still validated against the
    ledger (canonical editing-residue case).
    """
    units: list[_Unit] = []
    markers: list[tuple[str, int, str]] = []
    for path in sorted(Path(sections_dir).glob("*.tex")):
        raw = path.read_text(encoding="utf-8")
        cleaned = _exclude_regions(raw)
        raw_lines = raw.split("\n")
        clean_lines = cleaned.split("\n")
        rel = path.name
        pending: list[str] = []
        block_lines: list[tuple[int, str]] = []
        block_raw: list[tuple[int, str]] = []
        block_bound: list[str] = []

        def close_block():
            nonlocal block_lines, block_raw, block_bound
            if block_lines:
                _emit_block(rel, block_lines, block_bound, units, block_raw)
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
            stripped = clean_l.strip()
            if not stripped or STRUCTURAL_RE.match(stripped):
                close_block()
                continue
            if not block_lines:
                block_bound = pending
                pending = []
            block_lines.append((i, stripped))
            block_raw.append((i, COMMENT_RE.sub("", raw_l).strip()))
        close_block()
    return units, markers


def _is_methods_section(name: str, text: str) -> bool:
    if METHOD_RE.search(Path(name).stem):
        return True
    return any(METHOD_RE.search(m.group(1)) for m in SECTION_TITLE_RE.finditer(text))


# ------------------------------------------------------------- numeric audit


def _span_text(origin, materials_dir, cache):
    if origin not in cache:
        if origin.startswith("material:"):
            cache[origin] = _resolve_material(origin, materials_dir)[0]
        else:
            cache[origin] = None  # retrieval:/field_common have no line span
    return cache[origin]


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
            for conv in c.get("conversions") or []:
                fn = CONVERSIONS.get(conv)
                if fn is None:
                    continue
                for s in span_nums:
                    try:
                        sv = float(s)
                    except ValueError:
                        continue
                    if math.isclose(fn(sv), val, rel_tol=1e-9, abs_tol=1e-9):
                        return True
    return False


def audit_numbers(
    sections_dir: Path | str, claims: list[dict], materials_dir: Path | str
) -> list[str]:
    """Numeric provenance + binding violations (these gate the CLI exit code)."""
    violations: list[str] = []
    by_id = {c.get("id"): c for c in claims if isinstance(c, dict)}
    units, markers = _sentence_units(sections_dir)
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
    cache: dict[str, str | None] = {}
    for u in units:
        valid = [by_id[i] for i in u.bound if i in by_id]
        if u.file in methods:
            for c in valid:
                if c.get("evidence_level") == "L3" or c.get("boundary") == "related_work_only":
                    origin = c.get("origin", "")
                    loc = (
                        origin.split(":", 1)[1]
                        if origin.startswith("retrieval:")
                        else origin
                    )
                    violations.append(
                        f"{u.file}:{u.line}: L3 metadata claim '{c.get('id')}' "
                        f"({loc}) bound in methods section - metadata-only evidence "
                        f"cannot support method detail (boundary related_work_only)"
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


def _canonical_l3_deixis(u: _Unit, valid: list[dict], methods: set[str]) -> bool:
    """True iff the sentence is EXACTLY the canonical citation-level deixis
    that L3/related_work_only evidence supports (narrow exemption, report-only):
    bound to L3/related_work_only claim(s) + deixis shape (author et al. (year)
    + deixis verb + \\cite) + no data numbers beyond year/cite + not methods."""
    if not valid or u.file in methods or not u.raw:
        return False
    if not all(
        c.get("evidence_level") == "L3" or c.get("boundary") == "related_work_only"
        for c in valid
    ):
        return False
    if not DEIXIS_RE.search(u.raw):
        return False
    # u.text has math/cite/ref args/years blanked: any number left is data.
    return not NUMBER_RE.search(u.text)


def audit_strength_mismatch(sections_dir: Path | str, claims: list[dict]) -> dict:
    """Report-only strength mismatches. NO numeric budget/quota/gate anywhere.

    weakened_strong: L1/L2-backed sentence hedged with may/could/potentially/likely.
    overclaimed_weak: categorical sentence (none of the four hedge words) whose
    only support is L3/L4, or which has no ledger backing at all. Canonical
    L3 deixis ("X et al. (Year) addressed Y \\cite{...}" in related work, no
    data numbers) is exempt -- that form is what related_work_only supports.
    Each item carries disposition advice offering BOTH directions.
    """
    by_id = {c.get("id"): c for c in claims if isinstance(c, dict)}
    weakened: list[dict] = []
    overclaimed: list[dict] = []
    units, _markers = _sentence_units(sections_dir)
    files = {
        p.name: p.read_text(encoding="utf-8")
        for p in sorted(Path(sections_dir).glob("*.tex"))
    }
    methods = {name for name, txt in files.items() if _is_methods_section(name, txt)}
    for u in units:
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
            weakened.append({**base, "hedge_words": hedges, "advice": _ADVICE_WEAKENED})
        elif not hedges and not strong:
            if _canonical_l3_deixis(u, valid, methods):
                continue
            overclaimed.append({**base, "advice": _ADVICE_OVERCLAIMED})
    return {"weakened_strong": weakened, "overclaimed_weak": overclaimed}


# ------------------------------------------------------------------------ CLI


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Audit a graded claims ledger (grading + numeric provenance "
        "+ optional report-only strength mismatch)."
    )
    p.add_argument("claims", type=Path, help="claims.jsonl ledger path")
    p.add_argument("--materials", type=Path, required=True, help="materials dir")
    p.add_argument("--sections", type=Path, help="sections dir with *.tex drafts")
    p.add_argument(
        "--strength-report",
        action="store_true",
        help="print strength-mismatch report (report-only, non-gating; needs --sections)",
    )
    args = p.parse_args(argv)
    if args.strength_report and args.sections is None:
        p.error("--strength-report requires --sections")
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
    violations = audit_claims(args.claims, args.materials)
    claims: list[dict] = []
    if args.sections is not None:
        try:
            claims = load_claims(args.claims)
        except ValueError:
            claims = []  # parse error already reported by audit_claims
        violations = violations + audit_numbers(args.sections, claims, args.materials)
    for v in violations:
        print("VIOLATION: " + v)
    if args.strength_report:
        report = audit_strength_mismatch(args.sections, claims)
        print("STRENGTH MISMATCH REPORT (report-only, non-gating):")
        print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"{len(violations)} violation(s)")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())