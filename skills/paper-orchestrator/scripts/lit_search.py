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
    search_papers(query, limit=20, api_key=None, raise_on_429=False) -> list[dict]
    search_crossref(query, limit=20) -> list[dict]
    search_arxiv(query, limit=20) -> list[dict]
    dedupe_papers(papers) -> list[dict]
    enrich_fallback(papers, mode="crossref") -> list[dict]       # Crossref->arXiv->manual
    build_bibtex(paper) -> str                                   # one entry
    build_bibtex_set(papers) -> list[str]                        # unique citekeys
    assign_citekeys(papers, existing_keys=None) -> list[str]     # deterministic a/b/c
    prioritize(papers, keywords) -> list[dict]                   # difflib ranking
    build_ledger_draft(papers, start_index=1) -> list[dict]      # claims.jsonl rows
    build_numeric_map(papers) -> dict[str, str]                  # {"1": citekey}

CLI:
    python lit_search.py (--query "..." | --queries-from outline.json)
        [--limit 20] --out refs.jsonl [--bib refs.bib]
        [--source s2|crossref|arxiv|auto] [--fallback crossref|arxiv|off]
        [--append] [--existing-bib prev.bib] [--rank] [--keywords "..."]
        [--emit-ledger-draft claims_refs.jsonl] [--emit-numeric-map map.json]
        [--keep-l3-tldr] [--api-key KEY]

Key priority: --api-key > SEMANTIC_SCHOLAR_API_KEY > public tier. When no key is
available each S2 JSONL line is tagged ``"rate": "public-tier"``. The API key is
never printed (upstream scholar_utils.py:28 leaked it at import time -- fixed here).
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
from pathlib import Path

import requests

S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
# Upstream requested title,authors,venue,year,abstract,citationCount,journal,
# publicationDate (:68). We swap journal/publicationDate for url,externalIds,tldr
# to fill the normalized 10-key contract; paperId is requested explicitly.
S2_FIELDS = "paperId,title,authors,venue,year,abstract,citationCount,url,externalIds,tldr"
CROSSREF_URL = "https://api.crossref.org/works"
ARXIV_URL = "https://export.arxiv.org/api/query"
_ATOM = {"a": "http://www.w3.org/2005/Atom"}
_CONFERENCE_RE = re.compile(
    r"(?:\b(?:CVPR|ICCV|ECCV|NeurIPS|NIPS|ICML|ICLR|ACL|EMNLP|NAACL|COLING"
    r"|AAAI|IJCAI|KDD|SIGMOD|VLDB|SIGIR|WWW|WSDM|CHI|UIST|OSDI|SOSP|NSDI"
    r"|SIGCOMM|CCS|USENIX|PODS|STOC|FOCS|ICRA|IROS|RSS|CoRL|MICCAI|BMVC|WACV"
    r"|ACMMM|ICASSP|ICIP|ICSE|FSE|ASE|ISSTA|PLDI|POPL|OOPSLA|ASPLOS|ISCA"
    r"|MICRO|HPCA|Conference|Proceedings|Symposium|Workshop)\b"
    r"|\b(?:Proc|Conf)\.(?=\s|$))",
    re.IGNORECASE,
)
_BIB_KEY_RE = re.compile(r"@\w+\s*\{\s*([^,\s{}]+)\s*,")

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


def search_papers(
    query: str,
    limit: int = 20,
    api_key: str | None = None,
    raise_on_429: bool = False,
) -> list[dict]:
    """Search Semantic Scholar; return <= limit normalized 10-key rows.

    Key priority handled here for library use: explicit api_key > env > public tier.
    Persistent 429 (or other request failure) becomes an actionable SystemExit, not
    a bare exception (unless raise_on_429=True for --source auto fallback). The
    key is sent only in the X-API-KEY header, never printed.
    """
    if api_key is None:
        api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    headers = {"X-API-KEY": api_key} if api_key else {}
    params = {"query": query, "limit": limit, "fields": S2_FIELDS}
    try:
        resp = _get(S2_SEARCH_URL, params=params, headers=headers)
    except RateLimitError:
        if raise_on_429:
            raise
        _die(
            "Semantic Scholar 限流（HTTP 429）：公开层速率受限，退避重试后仍失败。"
            "建议：设置 SEMANTIC_SCHOLAR_API_KEY 提升配额，或稍后重试；"
            "也可改用 --source crossref/arxiv 或 --source auto，或走宿主联网检索兜底。"
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
            "建议稍后重试，或改用 --source crossref/arxiv / 宿主联网检索兜底。"
        )
        data = []
    return [_normalize(r) for r in data][:limit]


def _clean_crossref_item(it: dict) -> dict:
    title = (it.get("title") or [""])[0]
    authors: list[str] = []
    for a in it.get("author") or []:
        name = f"{a.get('given', '')} {a.get('family', '')}".strip()
        if name:
            authors.append(name)
    year = None
    for date_key in ("published-print", "published-online", "issued", "created"):
        parts = ((it.get(date_key) or {}).get("date-parts") or [[]])[0]
        if parts and isinstance(parts[0], int):
            year = parts[0]
            break
    raw_abs = it.get("abstract") or ""
    clean_abs = re.sub(r"<[^>]+>", " ", raw_abs)
    clean_abs = " ".join(clean_abs.split()) or None
    venue = (it.get("container-title") or [""])[0] or ""
    return {
        "paperId": None,
        "title": title,
        "year": year,
        "abstract": clean_abs,
        "url": it.get("URL"),
        "citationCount": it.get("is-referenced-by-count"),
        "venue": venue,
        "tldr": None,
        "authors": authors,
        "externalIds": {"DOI": it.get("DOI"), "ArXiv": None},
    }


def search_crossref(query: str, limit: int = 20) -> list[dict]:
    """Primary literature search via Crossref Works API -> normalized 10-key rows."""
    try:
        resp = _get(CROSSREF_URL, params={"query": query, "rows": limit})
        items = resp.json().get("message", {}).get("items", [])
    except requests.RequestException as e:
        _die(f"Crossref 请求失败：{e}。请检查网络连接或稍后重试。")
    except ValueError:
        _note("Crossref 响应体不是合法 JSON：按 0 行处理。")
        items = []
    return [_clean_crossref_item(it) for it in items[:limit]]


def _clean_arxiv_query(text: str) -> str:
    cleaned = text.replace('"', " ")
    return " ".join(cleaned.split())


def _parse_arxiv_entry(entry: ET.Element) -> dict:
    title_el = entry.find("a:title", _ATOM)
    title = " ".join((title_el.text or "").split()) if title_el is not None else ""
    summary_el = entry.find("a:summary", _ATOM)
    abstract = (
        " ".join((summary_el.text or "").split()) or None
        if summary_el is not None and summary_el.text
        else None
    )
    authors = [n.text.strip() for n in entry.findall("a:author/a:name", _ATOM) if n.text]
    idel = entry.find("a:id", _ATOM)
    raw_id = idel.text.strip() if idel is not None and idel.text else ""
    arxiv_id = re.sub(r"v\d+$", "", raw_id.split("/abs/")[-1]) if raw_id else None
    pub_el = entry.find("a:published", _ATOM)
    year = None
    if pub_el is not None and pub_el.text:
        ym = re.match(r"(\d{4})", pub_el.text.strip())
        if ym:
            year = int(ym.group(1))
    return {
        "paperId": None,
        "title": title,
        "year": year,
        "abstract": abstract,
        "url": raw_id or None,
        "citationCount": None,
        "venue": "",
        "tldr": None,
        "authors": authors,
        "externalIds": {"DOI": None, "ArXiv": arxiv_id},
    }


def search_arxiv(query: str, limit: int = 20) -> list[dict]:
    """Primary literature search via arXiv Atom API -> normalized 10-key rows."""
    q = _clean_arxiv_query(query)
    try:
        resp = _get(ARXIV_URL, params={"search_query": f"all:{q}", "max_results": limit})
        root = ET.fromstring(resp.text)
    except requests.RequestException as e:
        _die(f"arXiv 请求失败：{e}。请检查网络连接或稍后重试。")
    except ET.ParseError:
        _note("arXiv 响应 XML 解析失败：按 0 行处理。")
        return []
    entries = root.findall("a:entry", _ATOM)
    return [_parse_arxiv_entry(e) for e in entries[:limit]]


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
        parsed = _clean_crossref_item(it)
        return {
            "authors": parsed["authors"],
            "DOI": parsed["externalIds"].get("DOI"),
            "year": parsed["year"],
            "abstract": parsed["abstract"],
        }
    except Exception:
        return None


def _arxiv_lookup(title: str) -> dict | None:
    try:
        clean_title = _clean_arxiv_query(title)
        resp = _get(ARXIV_URL, params={"search_query": f'ti:"{clean_title}"', "max_results": 1})
        root = ET.fromstring(resp.text)
        entry = root.find("a:entry", _ATOM)
        if entry is None:
            return None
        parsed = _parse_arxiv_entry(entry)
        hit_title = parsed["title"]
        if not _title_similar(title, hit_title):
            _note(f"arXiv 候选题名相似度不足，跳过以避免错配：{hit_title!r}")
            return None
        return {
            "authors": parsed["authors"],
            "ArXiv": parsed["externalIds"].get("ArXiv"),
            "abstract": parsed["abstract"],
            "year": parsed["year"],
        }
    except Exception:
        return None


def enrich_fallback(papers: list[dict], mode: str = "crossref") -> list[dict]:
    """Fill missing authors / externalIds(DOI/ArXiv) / abstract / year via Crossref then arXiv.

    mode="crossref": try Crossref then arXiv; mode="arxiv": arXiv only;
    mode="off": return copies untouched. Missing authors/externalIds are flagged
    ``needs_manual:<field>``; missing abstract is NOT flagged needs_manual.
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
        need_abstract = not (p.get("abstract") or "").strip()
        need_year = not p.get("year")
        if need_authors or need_ids or need_abstract or need_year:
            title = p.get("title") or ""
            for src in sources:
                if not (need_authors or need_ids or need_abstract or need_year):
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
                if need_abstract and found.get("abstract"):
                    p["abstract"] = found["abstract"]
                    need_abstract = False
                if need_year and found.get("year"):
                    p["year"] = found["year"]
                    need_year = False
            manual = []
            if need_authors:
                manual.append("needs_manual:authors")
            if need_ids:
                manual.append("needs_manual:externalIds")
            if manual:
                p["needs_manual"] = manual
        out.append(p)
    return out


# --- dedupe + citekeys + BibTeX (deterministic, no LLM) --------------------

def _paper_ident_keys(p: dict) -> list[tuple[str, object]]:
    keys: list[tuple[str, object]] = []
    if p.get("paperId"):
        keys.append(("pid", str(p["paperId"]).strip()))
    ext = p.get("externalIds") or {}
    if ext.get("DOI"):
        keys.append(("doi", str(ext["DOI"]).strip().lower()))
    if ext.get("ArXiv"):
        keys.append(("arxiv", str(ext["ArXiv"]).strip().lower()))
    norm_t = " ".join((p.get("title") or "").lower().split())
    if norm_t:
        keys.append(("title_year", (norm_t, p.get("year"))))
    return keys


def _merge_paper(dst: dict, src: dict) -> None:
    if not dst.get("citekey") and src.get("citekey"):
        dst["citekey"] = src["citekey"]
    if not dst.get("paperId") and src.get("paperId"):
        dst["paperId"] = src["paperId"]
    if not dst.get("year") and src.get("year"):
        dst["year"] = src["year"]
    if not (dst.get("abstract") or "").strip() and (src.get("abstract") or "").strip():
        dst["abstract"] = src["abstract"]
    if not dst.get("url") and src.get("url"):
        dst["url"] = src["url"]
    if not dst.get("venue") and src.get("venue"):
        dst["venue"] = src["venue"]
    if not dst.get("tldr") and src.get("tldr"):
        dst["tldr"] = src["tldr"]
    if not dst.get("authors") and src.get("authors"):
        dst["authors"] = list(src["authors"])
    c_dst = dst.get("citationCount")
    c_src = src.get("citationCount")
    if isinstance(c_src, int) and (not isinstance(c_dst, int) or c_src > c_dst):
        dst["citationCount"] = c_src
    ext_d = dict(dst.get("externalIds") or {})
    ext_s = src.get("externalIds") or {}
    for k in ("DOI", "ArXiv"):
        if not ext_d.get(k) and ext_s.get(k):
            ext_d[k] = ext_s[k]
    dst["externalIds"] = ext_d


def dedupe_papers(papers: list[dict]) -> list[dict]:
    """Deduplicate papers across queries/sources by paperId/DOI/ArXiv/(title, year)."""
    merged: list[dict] = []
    seen_idx: dict[tuple[str, object], int] = {}
    for raw in papers:
        p = dict(raw)
        p["authors"] = list(p.get("authors") or [])
        p["externalIds"] = dict(p.get("externalIds") or {})
        ikeys = _paper_ident_keys(p)
        hit = next((seen_idx[ik] for ik in ikeys if ik in seen_idx), None)
        if hit is not None:
            _merge_paper(merged[hit], p)
            for ik in _paper_ident_keys(merged[hit]):
                seen_idx[ik] = hit
        else:
            idx = len(merged)
            merged.append(p)
            for ik in ikeys:
                seen_idx[ik] = idx
    return merged

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


def _load_bib_keys(bib_path: Path) -> set[str]:
    return set(_BIB_KEY_RE.findall(bib_path.read_text(encoding="utf-8")))


def assign_citekeys(
    papers: list[dict], existing_keys: set[str] | None = None
) -> list[str]:
    """Deterministic citekeys: slug(surname)+year+first title content word.

    Pre-assigned ``paper['citekey']`` and keys in ``existing_keys`` are locked
    forever so incremental appends never drift existing references. New papers
    disambiguate collisions using the first unused suffix.
    """
    has_locked = bool(existing_keys) or any(
        isinstance(p.get("citekey"), str) and p["citekey"].strip() for p in papers
    )
    if not has_locked:
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

    locked: set[str] = set(existing_keys or ())
    for p in papers:
        ck = p.get("citekey")
        if isinstance(ck, str) and ck.strip():
            locked.add(ck.strip())

    new_bases = [
        _base_citekey(p)
        for p in papers
        if not (isinstance(p.get("citekey"), str) and p["citekey"].strip())
    ]
    new_counts = Counter(new_bases)
    keys = []
    for p in papers:
        ck = p.get("citekey")
        if isinstance(ck, str) and ck.strip():
            keys.append(ck.strip())
            continue
        b = _base_citekey(p)
        has_suffix_group = any(k.startswith(b) and k != b for k in locked)
        if new_counts[b] == 1 and b not in locked and not has_suffix_group:
            cand = b
        else:
            idx = 0
            while True:
                cand = b + _letter(idx)
                if cand not in locked:
                    break
                idx += 1
        locked.add(cand)
        keys.append(cand)
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
    double-braced so the bst preserves its capitalization. Conference venues emit
    @inproceedings with booktitle; other venues emit @article with journal.
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
    is_conf = bool(venue and _CONFERENCE_RE.search(venue))
    entry_type = "inproceedings" if is_conf else ("article" if venue else "misc")
    lines = [f"@{entry_type}{{{key},"]
    lines.append(f"  author = {{{author_field}}},")
    lines.append("  title = {{" + _bib_escape(paper.get("title") or "") + "}},")
    if year:
        lines.append(f"  year = {{{year}}},")
    if venue:
        field_name = "booktitle" if is_conf else "journal"
        lines.append(f"  {field_name} = {{{_bib_escape(venue)}}},")
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


# --- ledger draft + numeric map generation ---------------------------------


def build_ledger_draft(
    papers: list[dict], start_index: int = 1
) -> list[dict]:
    """Generate claims.jsonl rows (L2 when abstract present, else L3)."""
    need_keys = any(not p.get("citekey") for p in papers)
    keys = assign_citekeys(papers) if need_keys else [p["citekey"] for p in papers]
    rows: list[dict] = []
    for idx, (p, ck) in enumerate(zip(papers, keys), start_index):
        has_abs = bool((p.get("abstract") or "").strip())
        level = "L2" if has_abs else "L3"
        boundary = "headline_only" if has_abs else "related_work_only"
        authors = p.get("authors") or []
        first = _surname(authors[0]) if authors else "Anonymous"
        who = f"{first} et al." if len(authors) > 1 else first
        year = p.get("year") or "n.d."
        title = " ".join((p.get("title") or "this topic").split())
        rows.append({
            "id": f"R{idx}",
            "claim": f"{who} ({year}) addressed {title}.",
            "origin": f"retrieval:{ck}",
            "evidence_level": level,
            "boundary": boundary,
        })
    return rows


def build_numeric_map(papers: list[dict]) -> dict[str, str]:
    """Build 1-based numeric citation bridge map from ordered papers."""
    need_keys = any(not p.get("citekey") for p in papers)
    keys = assign_citekeys(papers) if need_keys else [p["citekey"] for p in papers]
    return {str(i): k for i, k in enumerate(keys, 1)}


# --- CLI -------------------------------------------------------------------


def _fetch_query(
    query: str, limit: int, source: str, api_key: str | None
) -> tuple[list[dict], bool]:
    """Return (papers, used_s2)."""
    if source == "crossref":
        return search_crossref(query, limit=limit), False
    if source == "arxiv":
        return search_arxiv(query, limit=limit), False
    if source == "auto":
        try:
            return search_papers(query, limit=limit, api_key=api_key, raise_on_429=True), True
        except RateLimitError:
            _note(
                "Semantic Scholar 触发 429 限流，已按 --source auto 降级至 Crossref + arXiv 主检索。"
            )
            cr = search_crossref(query, limit=limit)
            ax = search_arxiv(query, limit=limit)
            return dedupe_papers(cr + ax)[:limit], False
    return search_papers(query, limit=limit, api_key=api_key), True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Scholarly search -> normalized JSONL (+ optional BibTeX / ledger draft / numeric map).",
    )
    qgroup = parser.add_mutually_exclusive_group(required=True)
    qgroup.add_argument("--query", help="single search query")
    qgroup.add_argument("--queries-from", type=Path, help="outline.json path (reads lit_strategy.queries)")
    parser.add_argument("--limit", type=int, default=20, help="max results per query (default 20)")
    parser.add_argument("--out", required=True, help="output refs.jsonl path")
    parser.add_argument("--bib", help="optional output refs.bib path")
    parser.add_argument(
        "--source",
        choices=["s2", "crossref", "arxiv", "auto"],
        default="s2",
        help="primary search backend (default s2; auto degrades to crossref+arxiv on 429)",
    )
    parser.add_argument("--fallback", choices=["crossref", "arxiv", "off"], default="crossref",
                        help="missing-field fallback chain (default crossref)")
    parser.add_argument("--append", action="store_true",
                        help="merge into existing --out JSONL while locking existing citekeys")
    parser.add_argument("--existing-bib", type=Path, default=None,
                        help="lock citekeys already present in an existing .bib file")
    parser.add_argument("--rank", action="store_true",
                        help="rank collected papers with prioritize()")
    parser.add_argument("--keywords", default=None,
                        help="optional ranking keywords (defaults to query/must_contain)")
    parser.add_argument("--emit-ledger-draft", type=Path, default=None,
                        help="write L2/L3 claims ledger draft JSONL")
    parser.add_argument("--emit-numeric-map", type=Path, default=None,
                        help="write 1-based numeric_map.json for latex_compose")
    parser.add_argument("--keep-l3-tldr", action="store_true",
                        help="keep AI-generated tldr on L3 (no-abstract) JSONL rows")
    parser.add_argument("--api-key", dest="api_key", default=None,
                        help="S2 API key (else SEMANTIC_SCHOLAR_API_KEY, else public tier)")
    args = parser.parse_args(argv)

    api_key = args.api_key or os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    queries: list[str] = []
    rank_terms: list[str] = []
    if args.query:
        queries = [args.query]
        rank_terms = args.query.split()
    else:
        if not args.queries_from.is_file():
            _die(f"outline file not found: {args.queries_from}")
        try:
            outline = json.loads(args.queries_from.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            _die(f"cannot read outline {args.queries_from}: {exc}")
        ls = outline.get("lit_strategy") if isinstance(outline, dict) else None
        qs = ls.get("queries") if isinstance(ls, dict) else None
        if not isinstance(qs, list) or not [q for q in qs if isinstance(q, str) and q.strip()]:
            _die(f"{args.queries_from}: missing non-empty lit_strategy.queries")
        queries = [q.strip() for q in qs if isinstance(q, str) and q.strip()]
        mc = ls.get("must_contain") if isinstance(ls, dict) else None
        rank_terms = list(queries) + ([x for x in mc if isinstance(x, str)] if isinstance(mc, list) else [])

    existing_rows: list[dict] = []
    out_path = Path(args.out)
    if args.append and out_path.is_file():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing_rows.append(json.loads(line))

    existing_keys: set[str] = set()
    if args.existing_bib is not None:
        if not args.existing_bib.is_file():
            _die(f"existing bib file not found: {args.existing_bib}")
        existing_keys |= _load_bib_keys(args.existing_bib)

    fetched: list[dict] = []
    used_s2_any = False
    for q in queries:
        batch, used_s2 = _fetch_query(q, args.limit, args.source, api_key)
        used_s2_any = used_s2_any or used_s2
        fetched.extend(batch)

    fetched = dedupe_papers(fetched)
    if args.fallback != "off":
        fetched = enrich_fallback(fetched, mode=args.fallback)

    if args.rank:
        kw_arg = args.keywords if args.keywords is not None else " ".join(rank_terms).split()
        fetched = prioritize(fetched, kw_arg)

    papers = dedupe_papers(existing_rows + fetched) if existing_rows else fetched

    # Assign set-wide unique citekeys; locked keys never drift.
    keys = assign_citekeys(papers, existing_keys=existing_keys or None)
    for p, k in zip(papers, keys):
        p["citekey"] = k

    with open(out_path, "w", encoding="utf-8") as f:
        for p in papers:
            row = dict(p)
            if not args.keep_l3_tldr and not (row.get("abstract") or "").strip():
                row["tldr"] = None
            if not api_key and used_s2_any and "rate" not in row:
                row["rate"] = "public-tier"
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    if args.bib:
        entries = [build_bibtex(p) for p in papers]
        with open(args.bib, "w", encoding="utf-8") as f:
            f.write("\n\n".join(entries) + ("\n" if entries else ""))

    if args.emit_ledger_draft:
        draft_rows = build_ledger_draft(papers)
        args.emit_ledger_draft.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in draft_rows),
            encoding="utf-8",
        )

    if args.emit_numeric_map:
        nmap = build_numeric_map(papers)
        args.emit_numeric_map.write_text(
            json.dumps(nmap, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    print(f"wrote {len(papers)} rows -> {args.out}" + (f"; bib -> {args.bib}" if args.bib else ""),
          file=sys.stderr)


if __name__ == "__main__":
    main()