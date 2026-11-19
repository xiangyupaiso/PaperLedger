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
# Adapted from upstream utils/scholar_utils.py @d9bae997 (PaperOrchestra).
# Ported: the Semantic Scholar /paper/search GET, the optional X-API-KEY header
# (:37), the query/limit/fields params (:65-69) and the timeout (:70, default
# raised 5s->10s). limit is now a parameter (upstream hardcoded 3 at :67).
# Fixed: removed the import-time API-key print (upstream :28) and the module-level
# env read (:27); the key is now resolved per call and never echoed.
# Removed model/extra coupling: thefuzz (:20,:87), python-dotenv (:23,:26) and the
# single-best-match fuzz threshold (:95-97) are gone; ranking uses stdlib difflib.
# Added (NOT present upstream, verified 0 hits repo-wide): authors flattened to
# list[str], externalIds (DOI/ArXiv) normalization, deterministic BibTeX assembly
# with collision-suffixed citekeys, and a Crossref -> arXiv -> needs_manual
# fallback chain. search_papers returns a normalized 10-key list (<= limit) rather
# than one raw match.

"""Standalone, model-free Semantic Scholar search CLI for the paper-orchestrator skill.

Runtime dependency: ``requests`` only (everything else is stdlib). No LLM calls.

Library surface:
    search_papers(query, limit=20, api_key=None) -> list[dict]   # 10 fixed keys
    enrich_fallback(papers, mode="crossref") -> list[dict]       # Crossref->arXiv->manual
    build_bibtex(paper) -> str                                   # one entry
    build_bibtex_set(papers) -> list[str]                        # unique citekeys
    assign_citekeys(papers) -> list[str]                         # deterministic a/b/c
    prioritize(papers, keywords) -> list[dict]                   # difflib ranking

CLI:
    python lit_search.py --query "..." --limit 20 --out refs.jsonl \
        [--bib refs.bib] [--fallback crossref|arxiv|off] [--api-key KEY]

Key priority: --api-key > SEMANTIC_SCHOLAR_API_KEY > public tier. When no key is
available each JSONL line is tagged ``"rate": "public-tier"``. The API key is never
printed (upstream scholar_utils.py:28 leaked it at import time -- fixed here).
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter

import requests

S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
# Upstream requested title,authors,venue,year,abstract,citationCount,journal,
# publicationDate (:68). We swap journal/publicationDate for url,externalIds,tldr
# to fill the normalized 10-key contract; paperId is requested explicitly.
S2_FIELDS = "paperId,title,authors,venue,year,abstract,citationCount,url,externalIds,tldr"
CROSSREF_URL = "https://api.crossref.org/works"
ARXIV_URL = "http://export.arxiv.org/api/query"
_ATOM = {"a": "http://www.w3.org/2005/Atom"}

# Words skipped when picking the title's first content word for a citekey.
_STOPWORDS = {
    "a", "an", "the", "of", "for", "on", "in", "to", "and", "or", "with",
    "via", "from", "by", "as", "at", "is", "are", "be", "using", "toward",
    "towards", "into", "over", "under",
}


class RateLimitError(RuntimeError):
    """Raised when HTTP 429 persists after backoff retries."""


def _die(msg: str) -> None:
    """Print an actionable message to stderr and exit non-zero (no bare traceback)."""
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def _get(url, params=None, headers=None, timeout=10, retries=4, backoff=1.0):
    """Unified GET with exponential backoff on 429/5xx.

    Returns the response on success. Raises RateLimitError if 429 persists,
    requests.HTTPError for other bad statuses, requests.RequestException on
    network failure. Callers decide whether to exit (search) or degrade (fallback).
    """
    resp = None
    for attempt in range(retries):
        resp = requests.get(url, params=params, headers=headers or {}, timeout=timeout)
        if resp.status_code in (429, 500, 502, 503, 504):
            if attempt < retries - 1:
                time.sleep(backoff * (2 ** attempt))
                continue
            if resp.status_code == 429:
                raise RateLimitError(f"429 rate limited after {retries} attempts: {url}")
        resp.raise_for_status()
        return resp
    resp.raise_for_status()  # pragma: no cover - loop always returns or raises
    return resp


def _normalize(r: dict) -> dict:
    """Map a raw S2 item to the fixed 10-key normalized row."""
    authors: list[str] = []
    for a in r.get("authors") or []:
        if isinstance(a, dict):
            if a.get("name"):
                authors.append(a["name"])
        elif isinstance(a, str):
            authors.append(a)
    ext = dict(r.get("externalIds") or {})
    ext.setdefault("DOI", None)
    ext.setdefault("ArXiv", None)
    tldr_raw = r.get("tldr")
    tldr = tldr_raw.get("text") if isinstance(tldr_raw, dict) else tldr_raw
    return {
        "paperId": r.get("paperId"),
        "title": r.get("title") or "",
        "year": r.get("year"),
        "abstract": r.get("abstract"),
        "url": r.get("url"),
        "citationCount": r.get("citationCount"),
        "venue": r.get("venue") or "",
        "tldr": tldr,
        "authors": authors,
        "externalIds": ext,
    }


def search_papers(query: str, limit: int = 20, api_key: str | None = None) -> list[dict]:
    """Search Semantic Scholar; return <= limit normalized 10-key rows.

    Key priority handled here for library use: explicit api_key > env > public tier.
    Persistent 429 (or other request failure) becomes an actionable SystemExit, not
    a bare exception. The key is sent only in the X-API-KEY header, never printed.
    """
    if api_key is None:
        api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    headers = {"X-API-KEY": api_key} if api_key else {}
    params = {"query": query, "limit": limit, "fields": S2_FIELDS}
    try:
        resp = _get(S2_SEARCH_URL, params=params, headers=headers)
    except RateLimitError:
        _die(
            "Semantic Scholar 限流（HTTP 429）：公开层速率受限，退避重试后仍失败。"
            "建议：设置 SEMANTIC_SCHOLAR_API_KEY 提升配额，或稍后重试；"
            "也可改用 --fallback crossref/arxiv，或走宿主联网检索兜底。"
        )
    except requests.RequestException as e:
        _die(f"Semantic Scholar 请求失败：{e}。请检查网络连接或稍后重试。")
    try:
        data = resp.json().get("data", [])
    except ValueError:
        # F10: an unparseable body (gateway HTML, truncated JSON) is NOT the
        # same as "no results" -- say so on stderr instead of silent 0 rows.
        _note(
            "Semantic Scholar 响应体不是合法 JSON（区别于“无结果”）：按 0 行处理。"
            "建议稍后重试，或改用 --fallback crossref/arxiv / 宿主联网检索兜底。"
        )
        data = []
    return [_normalize(r) for r in data][:limit]


# --- fallback chain: Crossref -> arXiv -> needs_manual ---------------------

# Minimum difflib title similarity to trust a Crossref/arXiv candidate. Mirrors
# upstream's >70 fuzz gate (scholar_utils.py:95-97), which the port otherwise
# dropped; below this the hit is treated as a different work and we fall through
# to the next source / needs_manual rather than silently attaching wrong metadata.
FALLBACK_MATCH_THRESHOLD = 0.70


def _note(msg: str) -> None:
    """One-line stderr signal for the host (never carries the API key)."""
    print(msg, file=sys.stderr)


def _title_similar(query: str, hit: str) -> bool:
    q = " ".join((query or "").lower().split())
    h = " ".join((hit or "").lower().split())
    return difflib.SequenceMatcher(None, q, h).ratio() >= FALLBACK_MATCH_THRESHOLD


def _crossref_lookup(title: str) -> dict | None:
    try:
        resp = _get(CROSSREF_URL, params={"query.title": title, "rows": 1})
        items = resp.json().get("message", {}).get("items", [])
        if not items:
            return None
        it = items[0]
        hit_title = (it.get("title") or [""])[0]
        if not _title_similar(title, hit_title):
            _note(f"Crossref 候选题名相似度不足，跳过以避免错配：{hit_title!r}")
            return None
        authors = []
        for a in it.get("author") or []:
            name = f"{a.get('given', '')} {a.get('family', '')}".strip()
            if name:
                authors.append(name)
        return {"authors": authors, "DOI": it.get("DOI")}
    except Exception:
        return None


def _arxiv_lookup(title: str) -> dict | None:
    try:
        resp = _get(ARXIV_URL, params={"search_query": f'ti:"{title}"', "max_results": 1})
        root = ET.fromstring(resp.text)
        entry = root.find("a:entry", _ATOM)
        if entry is None:
            return None
        title_el = entry.find("a:title", _ATOM)
        hit_title = title_el.text if title_el is not None and title_el.text else ""
        if not _title_similar(title, hit_title):
            _note(f"arXiv 候选题名相似度不足，跳过以避免错配：{hit_title!r}")
            return None
        authors = [n.text.strip() for n in entry.findall("a:author/a:name", _ATOM) if n.text]
        arxiv_id = None
        idel = entry.find("a:id", _ATOM)
        if idel is not None and idel.text:
            arxiv_id = re.sub(r"v\d+$", "", idel.text.strip().split("/abs/")[-1])
        return {"authors": authors, "ArXiv": arxiv_id}
    except Exception:
        return None


def enrich_fallback(papers: list[dict], mode: str = "crossref") -> list[dict]:
    """Fill missing authors / externalIds(DOI/ArXiv) via Crossref then arXiv.

    mode="crossref": try Crossref then arXiv; mode="arxiv": arXiv only;
    mode="off": return copies untouched. Whatever is still missing is flagged
    ``needs_manual:<field>`` (a signal for the host's own web retrieval).
    """
    if mode == "off":
        return [dict(p) for p in papers]
    sources = ["crossref", "arxiv"] if mode == "crossref" else ["arxiv"]
    out = []
    for p in papers:
        p = dict(p)
        p["authors"] = list(p.get("authors") or [])
        p["externalIds"] = dict(p.get("externalIds") or {})
        ext = p["externalIds"]
        need_authors = not p["authors"]
        need_ids = not ext.get("DOI") and not ext.get("ArXiv")
        if need_authors or need_ids:
            title = p.get("title") or ""
            for src in sources:
                if not (need_authors or need_ids):
                    break
                found = _crossref_lookup(title) if src == "crossref" else _arxiv_lookup(title)
                if not found:
                    continue
                if need_authors and found.get("authors"):
                    p["authors"] = found["authors"]
                    need_authors = False
                if need_ids:
                    if found.get("DOI"):
                        ext["DOI"] = found["DOI"]
                    if found.get("ArXiv"):
                        ext["ArXiv"] = found["ArXiv"]
                    need_ids = not ext.get("DOI") and not ext.get("ArXiv")
            manual = []
            if need_authors:
                manual.append("needs_manual:authors")
            if need_ids:
                manual.append("needs_manual:externalIds")
            if manual:
                p["needs_manual"] = manual
        out.append(p)
    return out


# --- citekeys + BibTeX (deterministic, no LLM) -----------------------------

def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", s.lower()) or "anon"


def _surname(author: str) -> str:
    author = author.strip()
    if "," in author:
        return author.split(",", 1)[0].strip()
    parts = author.split()
    return parts[-1] if parts else author


def _first_content_word(title: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", title.lower())
    for w in words:
        if w not in _STOPWORDS:
            return w
    return words[0] if words else "untitled"


def _base_citekey(paper: dict) -> str:
    authors = paper.get("authors") or []
    surname = _surname(authors[0]) if authors else "anon"
    year = paper.get("year")
    year_s = str(year) if year else ""
    word = _first_content_word(paper.get("title") or "")
    return f"{_slug(surname)}{year_s}{_slug(word)}"


def _letter(i: int) -> str:
    """0->a, 1->b, ... 25->z, 26->aa (collision suffix)."""
    s = ""
    i += 1
    while i > 0:
        i, r = divmod(i - 1, 26)
        s = chr(97 + r) + s
    return s


def assign_citekeys(papers: list[dict]) -> list[str]:
    """Deterministic citekeys: slug(surname)+year+first title content word.

    Unique keys stay bare; members of a collision group get a/b/c suffixes in
    input order. Same input set/order -> same keys.
    """
    bases = [_base_citekey(p) for p in papers]
    counts = Counter(bases)
    seen: dict[str, int] = {}
    keys = []
    for b in bases:
        if counts[b] == 1:
            keys.append(b)
        else:
            i = seen.get(b, 0)
            seen[b] = i + 1
            keys.append(b + _letter(i))
    return keys


# BibTeX/LaTeX special characters -> escaped forms. Single-pass substitution so
# the backslashes/braces introduced by replacements are not themselves re-escaped.
# Braces map to text-mode glyph commands (\textbraceleft/\textbraceright), NOT \{/\}:
# traditional bibtex's scanner counts every literal { / } regardless of a preceding
# backslash (bibtex.web 5894-5922), so \{ would leave a net imbalance on a lone brace.
# The terminating {} is brace-balanced (net 0) and stops TeX reading a following
# letter into the control-word name (bare \textbraceleftG would be undefined).
# \lbrace/\rbrace are math-mode only and deliberately avoided.
_BIB_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "#": r"\#",
    "_": r"\_",
    "$": r"\$",
    "{": r"\textbraceleft{}",
    "}": r"\textbraceright{}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_BIB_SPECIAL_RE = re.compile("[" + re.escape("".join(_BIB_SPECIAL)) + "]")


def _bib_escape(value) -> str:
    """Escape the ten LaTeX/BibTeX special characters in an interpolated value."""
    return _BIB_SPECIAL_RE.sub(lambda m: _BIB_SPECIAL[m.group(0)], str(value))


def build_bibtex(paper: dict) -> str:
    """One BibTeX entry. Uses paper['citekey'] if assigned, else the base scheme.

    Every interpolated value is LaTeX-escaped (& % # _ $ { } \\ ~ ^); the title is
    double-braced so the bst preserves its capitalization.
    """
    key = paper.get("citekey") or _base_citekey(paper)
    authors = paper.get("authors") or []
    author_field = " and ".join(_bib_escape(a) for a in authors) if authors else "Anonymous"
    ext = paper.get("externalIds") or {}
    doi = ext.get("DOI")
    arxiv = ext.get("ArXiv")
    venue = paper.get("venue") or ""
    year = paper.get("year")
    url = paper.get("url") or ""
    entry_type = "article" if venue else "misc"
    lines = [f"@{entry_type}{{{key},"]
    lines.append(f"  author = {{{author_field}}},")
    lines.append("  title = {{" + _bib_escape(paper.get("title") or "") + "}},")
    if year:
        lines.append(f"  year = {{{year}}},")
    if venue:
        lines.append(f"  journal = {{{_bib_escape(venue)}}},")
    if doi:
        lines.append(f"  doi = {{{_bib_escape(doi)}}},")
    if arxiv:
        lines.append(f"  eprint = {{{_bib_escape(arxiv)}}},")
        lines.append("  archivePrefix = {arXiv},")
    if url:
        lines.append(f"  url = {{{_bib_escape(url)}}},")
    lines.append("}")
    return "\n".join(lines)


def build_bibtex_set(papers: list[dict]) -> list[str]:
    """BibTeX entries with set-wide unique citekeys (collision-suffixed)."""
    keys = assign_citekeys(papers)
    entries = []
    for p, k in zip(papers, keys):
        pp = dict(p)
        pp["citekey"] = k
        entries.append(build_bibtex(pp))
    return entries


# --- ranking (thefuzz -> stdlib difflib) -----------------------------------

def prioritize(papers: list[dict], keywords) -> list[dict]:
    """Rank papers by relevance to keywords using stdlib difflib (no thefuzz).

    Replaces upstream's single-best-match fuzz.ratio (:87,:95-97) with a ranked
    list. Score = SequenceMatcher similarity of the keyword string vs the title,
    plus a small bonus for keyword presence (title weighted over abstract).
    """
    if isinstance(keywords, str):
        keywords = keywords.split()
    kws = [k.lower() for k in keywords if k]
    query = " ".join(kws)

    def score(p: dict) -> float:
        title = (p.get("title") or "").lower()
        abstract = (p.get("abstract") or "").lower()
        sim = difflib.SequenceMatcher(None, query, title).ratio()
        bonus = 0.0
        for k in kws:
            if k in title:
                bonus += 0.2
            elif k in abstract:
                bonus += 0.05
        return sim + bonus

    return sorted(papers, key=score, reverse=True)


# --- CLI -------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Semantic Scholar search -> normalized JSONL (+ optional BibTeX).",
    )
    parser.add_argument("--query", required=True, help="search query")
    parser.add_argument("--limit", type=int, default=20, help="max results (default 20)")
    parser.add_argument("--out", required=True, help="output refs.jsonl path")
    parser.add_argument("--bib", help="optional output refs.bib path")
    parser.add_argument("--fallback", choices=["crossref", "arxiv", "off"], default="crossref",
                        help="missing-field fallback chain (default crossref)")
    parser.add_argument("--api-key", dest="api_key", default=None,
                        help="S2 API key (else SEMANTIC_SCHOLAR_API_KEY, else public tier)")
    args = parser.parse_args(argv)

    api_key = args.api_key or os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    papers = search_papers(args.query, limit=args.limit, api_key=api_key)
    if args.fallback != "off":
        papers = enrich_fallback(papers, mode=args.fallback)

    # Assign set-wide unique citekeys; ledger and refs.bib share them.
    keys = assign_citekeys(papers)
    for p, k in zip(papers, keys):
        p["citekey"] = k

    with open(args.out, "w", encoding="utf-8") as f:
        for p in papers:
            row = dict(p)
            if not api_key:
                row["rate"] = "public-tier"
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    if args.bib:
        entries = [build_bibtex(p) for p in papers]
        with open(args.bib, "w", encoding="utf-8") as f:
            f.write("\n\n".join(entries) + ("\n" if entries else ""))

    print(f"wrote {len(papers)} rows -> {args.out}" + (f"; bib -> {args.bib}" if args.bib else ""),
          file=sys.stderr)


if __name__ == "__main__":
    main()