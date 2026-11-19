"""Tests for lit_search.py (Task 3).

All network access is monkeypatched -- no live calls in the automated suite.
The six mandated tests pin the ported/added behaviour; a seventh covers the
``prioritize`` ranking interface (thefuzz -> stdlib difflib).
"""
import importlib
import json
import re

import pytest
import requests

import lit_search


# --- helpers ---------------------------------------------------------------

class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


def make_paper(**kw):
    """A normalized 10-key row; override fields per scenario."""
    base = {
        "paperId": "pid",
        "title": "Deep Learning for Vision",
        "year": 2024,
        "abstract": "abs",
        "url": "https://example.org/p",
        "citationCount": 1,
        "venue": "NeurIPS",
        "tldr": "tldr text",
        "authors": ["Wei Zhang"],
        "externalIds": {"DOI": "10.1/aaa", "ArXiv": None},
    }
    base.update(kw)
    return base


RAW_S2_ITEM = {
    "paperId": "abc123",
    "title": "Attention Is All You Need",
    "year": 2017,
    "abstract": "We propose a new network architecture.",
    "url": "https://www.semanticscholar.org/paper/abc123",
    "citationCount": 100000,
    "venue": "NeurIPS",
    "tldr": {"model": "tldr@v2", "text": "Transformer paper."},
    "authors": [
        {"authorId": "1", "name": "Ashish Vaswani"},
        {"authorId": "2", "name": "Noam Shazeer"},
    ],
    "externalIds": {"DOI": "10.5555/3295222.3295349", "ArXiv": "1706.03762", "CorpusId": 123},
}

TEN_KEYS = {
    "paperId", "title", "year", "abstract", "url",
    "citationCount", "venue", "tldr", "authors", "externalIds",
}


# --- 1. normalized rows, exactly 10 keys -----------------------------------

def test_returns_normalized_rows_10_keys(monkeypatch):
    seen_params = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        assert "semanticscholar" in url
        seen_params.update(params or {})
        return FakeResponse(200, {"data": [RAW_S2_ITEM]})

    monkeypatch.setattr(lit_search.requests, "get", fake_get)
    rows = lit_search.search_papers("attention", limit=20, api_key="k")

    assert len(rows) == 1
    row = rows[0]
    assert set(row) == TEN_KEYS
    # authors flattened to list[str]
    assert row["authors"] == ["Ashish Vaswani", "Noam Shazeer"]
    assert all(isinstance(a, str) for a in row["authors"])
    # externalIds carries DOI / ArXiv
    assert row["externalIds"]["DOI"] == "10.5555/3295222.3295349"
    assert row["externalIds"]["ArXiv"] == "1706.03762"
    assert row["paperId"] == "abc123"
    assert row["tldr"] == "Transformer paper."
    # the request actually asked for the fields we normalize
    assert "externalIds" in seen_params["fields"]
    assert "authors" in seen_params["fields"]


# --- 2. API key never printed (nails upstream :28 bug) ---------------------

def test_api_key_never_printed(monkeypatch, capsys):
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "sk-SECRETTEST")
    # Re-executing module top level must not leak the key (upstream printed at import).
    importlib.reload(lit_search)
    out, err = capsys.readouterr()
    assert "sk-SECRETTEST" not in out
    assert "sk-SECRETTEST" not in err

    headers_seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        headers_seen.update(headers or {})
        return FakeResponse(200, {"data": []})

    monkeypatch.setattr(lit_search.requests, "get", fake_get)
    lit_search.search_papers("q")  # api_key None -> reads env, uses it, never prints
    out, err = capsys.readouterr()
    assert "sk-SECRETTEST" not in out
    assert "sk-SECRETTEST" not in err
    # key WAS read and sent in the header -- just never echoed
    assert headers_seen.get("X-API-KEY") == "sk-SECRETTEST"


# --- 3. public-tier marker on CLI JSONL when no key ------------------------

def test_public_tier_marked_when_no_key(monkeypatch, tmp_path):
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)

    def fake_get(url, params=None, headers=None, timeout=None):
        return FakeResponse(200, {"data": [RAW_S2_ITEM]})

    monkeypatch.setattr(lit_search.requests, "get", fake_get)

    # no key -> every line tagged public-tier
    out_nokey = tmp_path / "nokey.jsonl"
    lit_search.main(["--query", "q", "--limit", "3", "--out", str(out_nokey), "--fallback", "off"])
    lines = out_nokey.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]).get("rate") == "public-tier"

    # with key -> no public-tier marker
    out_key = tmp_path / "key.jsonl"
    lit_search.main(["--query", "q", "--limit", "3", "--out", str(out_key),
                     "--fallback", "off", "--api-key", "sk-XYZ"])
    row = json.loads(out_key.read_text(encoding="utf-8").splitlines()[0])
    assert "rate" not in row


# --- 4. persistent 429 -> backoff retries then actionable SystemExit -------

def test_429_retries_then_actionable_error(monkeypatch, capsys):
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    calls = {"n": 0}
    sleeps = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["n"] += 1
        return FakeResponse(429, {"error": "rate limited"})

    monkeypatch.setattr(lit_search.requests, "get", fake_get)
    monkeypatch.setattr(lit_search.time, "sleep", lambda s: sleeps.append(s))

    with pytest.raises(SystemExit) as exc:
        lit_search.search_papers("q", api_key=None)

    assert exc.value.code != 0          # actionable exit, not a bare traceback
    assert calls["n"] >= 2              # actually retried
    assert len(sleeps) >= 1             # with backoff
    assert "限流" in capsys.readouterr().err


# --- 5. bibtex: author + doi lines, unique citekeys on collision -----------

def test_bibtex_has_author_and_doi_and_unique_citekeys():
    p1 = make_paper(title="Deep Learning for Vision",
                    externalIds={"DOI": "10.1/aaa", "ArXiv": None})
    p2 = make_paper(title="Deep Learning for Language",
                    externalIds={"DOI": "10.1/bbb", "ArXiv": None})
    # same first-author surname (Zhang) + same year (2024) + same first
    # content word (deep) -> base citekey collides, must disambiguate a/b.
    entries = lit_search.build_bibtex_set([p1, p2])
    keys = [re.match(r"@\w+\{([^,]+),", e).group(1) for e in entries]
    assert keys[0] != keys[1]
    assert keys[0].endswith("a") and keys[1].endswith("b")
    for e in entries:
        assert "author" in e and "Wei Zhang" in e
        assert "doi" in e
    assert "10.1/aaa" in entries[0]
    assert "10.1/bbb" in entries[1]
    # single-paper entry also carries author + doi
    single = lit_search.build_bibtex(p1)
    assert "author" in single and "doi" in single
    # deterministic given the same input set
    assert lit_search.build_bibtex_set([p1, p2]) == entries


# --- 6. fallback order: crossref -> arxiv -> needs_manual ------------------

CROSSREF_HIT = {
    "message": {"items": [{
        "DOI": "10.1234/found",
        "author": [{"given": "Wei", "family": "Zhang"}, {"given": "Li", "family": "Wang"}],
        "title": ["Deep Learning for Vision"],
    }]}
}
CROSSREF_EMPTY = {"message": {"items": []}}
ARXIV_HIT = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<feed xmlns="http://www.w3.org/2005/Atom">'
    "<entry>"
    "<id>http://arxiv.org/abs/2401.01234v1</id>"
    "<title>Deep Learning for Vision</title>"
    "<author><name>Wei Zhang</name></author>"
    "<author><name>Li Wang</name></author>"
    "</entry>"
    "</feed>"
)
ARXIV_EMPTY = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'


def test_enrich_fallback_order_crossref_then_arxiv_then_manual(monkeypatch):
    calls = []

    def route(crossref_body, arxiv_body):
        def fake_get(url, params=None, headers=None, timeout=None):
            calls.append(url)
            if "crossref" in url:
                return FakeResponse(200, crossref_body)
            if "arxiv" in url:
                return FakeResponse(200, text=arxiv_body)
            raise AssertionError(f"unexpected url {url}")
        return fake_get

    missing = dict(authors=[], externalIds={"DOI": None, "ArXiv": None})

    # Scenario A: Crossref satisfies both fields -> arXiv never consulted.
    calls.clear()
    monkeypatch.setattr(lit_search.requests, "get", route(CROSSREF_HIT, ARXIV_HIT))
    out = lit_search.enrich_fallback([make_paper(**missing)])[0]
    assert out["authors"] == ["Wei Zhang", "Li Wang"]
    assert out["externalIds"]["DOI"] == "10.1234/found"
    assert not any("arxiv" in c for c in calls)
    assert "needs_manual" not in out

    # Scenario B: Crossref empty -> arXiv fills authors + ArXiv id, in order.
    calls.clear()
    monkeypatch.setattr(lit_search.requests, "get", route(CROSSREF_EMPTY, ARXIV_HIT))
    out = lit_search.enrich_fallback([make_paper(**missing)])[0]
    assert out["authors"] == ["Wei Zhang", "Li Wang"]
    assert out["externalIds"]["ArXiv"] == "2401.01234"
    assert any("crossref" in c for c in calls) and any("arxiv" in c for c in calls)
    assert next(i for i, c in enumerate(calls) if "crossref" in c) < \
           next(i for i, c in enumerate(calls) if "arxiv" in c)
    assert "needs_manual" not in out

    # Scenario C: both fail -> needs_manual markers for each missing field.
    calls.clear()
    monkeypatch.setattr(lit_search.requests, "get", route(CROSSREF_EMPTY, ARXIV_EMPTY))
    out = lit_search.enrich_fallback([make_paper(**missing)])[0]
    assert "needs_manual:authors" in out["needs_manual"]
    assert "needs_manual:externalIds" in out["needs_manual"]


# --- 7. prioritize ranks via stdlib difflib (no thefuzz) -------------------

def test_prioritize_ranks_by_difflib():
    p_match = make_paper(title="Attention Is All You Need", abstract="transformer attention")
    p_off = make_paper(title="A Survey of Database Systems", abstract="relational algebra")
    ranked = lit_search.prioritize([p_off, p_match], ["transformer", "attention"])
    assert ranked[0] is p_match
    assert len(ranked) == 2
    # accepts a plain string of keywords too
    assert lit_search.prioritize([p_off, p_match], "transformer attention")[0] is p_match


# --- 8. BibTeX escapes special chars; title double-braced (review fix 1) ----

def test_bibtex_escapes_special_chars_and_double_braces_title():
    # all ten LaTeX/BibTeX specials & % # _ $ { } \ ~ ^ in the author alone
    p = make_paper(
        authors=["A&B%C#D_E$F{G}H\\I~J^K"],
        title="T & % # _ $ { } \\ ~ ^",
        venue="V & W",
        externalIds={"DOI": "10.1/x_y%z", "ArXiv": None},
        url="https://e.org/a_b%c~d&e#f",
    )
    e = lit_search.build_bibtex(p)
    # exact escaped author covers every special character (braces -> text-mode
    # glyph commands with a terminating {} so they stay brace-balanced and do not
    # merge into a following letter as a TeX control word)
    assert (
        r"A\&B\%C\#D\_E\$F\textbraceleft{}G\textbraceright{}H\textbackslash{}I\textasciitilde{}J\textasciicircum{}K"
        in e
    )
    # title is double-braced (preserve capitalization under the bst) AND escaped
    assert "title = {{" in e
    assert (
        r"T \& \% \# \_ \$ \textbraceleft{} \textbraceright{} \textbackslash{} \textasciitilde{} \textasciicircum{}"
        in e
    )
    # venue / doi / url values escaped too
    assert r"journal = {V \& W}" in e
    assert r"doi = {10.1/x\_y\%z}" in e
    assert r"url = {https://e.org/a\_b\%c\textasciitilde{}d\&e\#f}" in e
    # no raw unescaped specials survive in the author value
    assert "A&B" not in e and "H\\I" not in e


# --- 9. fallback rejects dissimilar-title hits (review fix 2) --------------

def test_fallback_rejects_dissimilar_title_hit(monkeypatch):
    calls = []
    wrong_title = "Quantum Chromodynamics at Finite Temperature"
    crossref_wrong = {"message": {"items": [{
        "DOI": "10.9999/wrong",
        "author": [{"given": "Wrong", "family": "Author"}],
        "title": [wrong_title],
    }]}}
    arxiv_wrong = (
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        "<entry><id>http://arxiv.org/abs/9999.99999v1</id>"
        f"<title>{wrong_title}</title>"
        "<author><name>Wrong Author</name></author></entry></feed>"
    )

    def route(crossref_body, arxiv_body):
        def fake_get(url, params=None, headers=None, timeout=None):
            calls.append(url)
            if "crossref" in url:
                return FakeResponse(200, crossref_body)
            if "arxiv" in url:
                return FakeResponse(200, text=arxiv_body)
            raise AssertionError(f"unexpected url {url}")
        return fake_get

    missing = dict(authors=[], externalIds={"DOI": None, "ArXiv": None})

    # D: dissimilar Crossref hit must be rejected; arXiv empty -> needs_manual,
    #    and the wrong DOI/authors must NOT be attached to the row.
    calls.clear()
    monkeypatch.setattr(lit_search.requests, "get", route(crossref_wrong, ARXIV_EMPTY))
    out = lit_search.enrich_fallback([make_paper(**missing)])[0]
    assert any("crossref" in c for c in calls)          # consulted, then gated out
    assert out["externalIds"].get("DOI") is None
    assert out["authors"] == []
    assert "needs_manual:externalIds" in out["needs_manual"]
    assert "needs_manual:authors" in out["needs_manual"]

    # E: Crossref empty; dissimilar arXiv hit rejected -> needs_manual, no wrong id.
    calls.clear()
    monkeypatch.setattr(lit_search.requests, "get", route(CROSSREF_EMPTY, arxiv_wrong))
    out = lit_search.enrich_fallback([make_paper(**missing)])[0]
    assert any("arxiv" in c for c in calls)
    assert out["externalIds"].get("ArXiv") is None
    assert out["authors"] == []
    assert "needs_manual:externalIds" in out["needs_manual"]

    # F: a near-match (not byte-identical) title is still accepted -> the gate is
    #    similarity-based, not exact equality. make_paper title: "Deep Learning for Vision".
    calls.clear()
    crossref_near = {"message": {"items": [{
        "DOI": "10.1/near",
        "author": [{"given": "Wei", "family": "Zhang"}],
        "title": ["Deep Learning for Vision."],
    }]}}
    monkeypatch.setattr(lit_search.requests, "get", route(crossref_near, ARXIV_EMPTY))
    out = lit_search.enrich_fallback([make_paper(**missing)])[0]
    assert out["externalIds"].get("DOI") == "10.1/near"
    assert out["authors"] == ["Wei Zhang"]


# --- 10. lone-brace title stays brace-balanced for traditional bibtex -------

def test_bibtex_lone_brace_title_brace_balanced_for_traditional_bibtex():
    # Traditional bibtex's scanner counts EVERY literal { / } (backslash is just
    # an othercases char, no lookahead -- bibtex.web 5894-5922), so escaping a
    # brace as \{ / \} still leaves a net imbalance. The escape must contribute
    # net-zero literal braces. natbib + ieeenat_fullname.bst = traditional bibtex.
    p = make_paper(title="Scaling { Laws")           # lone open brace, no close
    e = lit_search.build_bibtex(p)
    assert r"\textbraceleft" in e                    # text-mode brace glyph
    assert r"\{" not in e                            # no backslash-brace left
    assert e.count("{") == e.count("}")              # net-zero literal-brace balance

    p2 = make_paper(title="Laws } Scaling")          # lone close brace
    e2 = lit_search.build_bibtex(p2)
    assert r"\textbraceright" in e2
    assert e2.count("{") == e2.count("}")

    p3 = make_paper(title="A { B { C } D")           # 2 open vs 1 close (net +1 raw)
    e3 = lit_search.build_bibtex(p3)
    assert e3.count("{") == e3.count("}")

# --- 11. malformed JSON body warns (distinct from no results) — fix-wave F10

def test_malformed_json_warns_not_silent(monkeypatch, capsys):
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)

    def bad_json_get(url, params=None, headers=None, timeout=None):
        return FakeResponse(200, None, text="<html>gateway error</html>")

    monkeypatch.setattr(lit_search.requests, "get", bad_json_get)
    capsys.readouterr()
    rows = lit_search.search_papers("q", api_key="k")
    assert rows == []
    err = capsys.readouterr().err
    assert "JSON" in err, "unparseable body must be distinguished from no results"

    # a well-formed empty result set stays silent (no false warning)
    def empty_get(url, params=None, headers=None, timeout=None):
        return FakeResponse(200, {"data": []})

    monkeypatch.setattr(lit_search.requests, "get", empty_get)
    capsys.readouterr()
    assert lit_search.search_papers("q", api_key="k") == []
    assert capsys.readouterr().err == ""


# --- 12. CLI --bib write branch — fix-wave F14 ------------------------------

def test_cli_bib_write_branch(monkeypatch, tmp_path):
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)

    def fake_get(url, params=None, headers=None, timeout=None):
        return FakeResponse(200, {"data": [RAW_S2_ITEM]})

    monkeypatch.setattr(lit_search.requests, "get", fake_get)
    out = tmp_path / "refs.jsonl"
    bib = tmp_path / "refs.bib"
    lit_search.main([
        "--query", "attention", "--limit", "5", "--out", str(out),
        "--bib", str(bib), "--fallback", "off", "--api-key", "sk-X",
    ])
    assert bib.is_file()
    entries = bib.read_text(encoding="utf-8")
    keys = re.findall(r"@\w+\{([^,]+),", entries)
    assert keys == ["vaswani2017attention"]
    assert "Ashish Vaswani" in entries and "Noam Shazeer" in entries
    # the JSONL row and the bib entry share the same citekey
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["citekey"] == keys[0]


# --- 13. Phase 1 tests ------------------------------------------------------


def test_bibtex_conference_uses_inproceedings_and_journal_uses_article():
    conf_p = make_paper(venue="CVPR 2024", externalIds={"DOI": "10.1/c", "ArXiv": None})
    jour_p = make_paper(venue="Nature Machine Intelligence", externalIds={"DOI": "10.1/j", "ArXiv": None})
    conf_bib = lit_search.build_bibtex(conf_p)
    jour_bib = lit_search.build_bibtex(jour_p)
    assert conf_bib.startswith("@inproceedings{")
    assert "booktitle = {CVPR 2024}" in conf_bib
    assert jour_bib.startswith("@article{")
    assert "journal = {Nature Machine Intelligence}" in jour_bib


def test_arxiv_https_quote_clean_and_summary_backfill(monkeypatch):
    seen = {}
    arxiv_with_summary = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<entry>"
        "<id>https://arxiv.org/abs/2402.09999v2</id>"
        '<title>Quoted "Method" Analysis</title>'
        "<summary>  We analyze quoted methods empirically.  </summary>"
        "<published>2024-02-15T00:00:00Z</published>"
        "<author><name>Jane Doe</name></author>"
        "</entry>"
        "</feed>"
    )

    def fake_get(url, params=None, headers=None, timeout=None):
        seen["url"] = url
        seen["params"] = params
        if "crossref" in url:
            return FakeResponse(200, CROSSREF_EMPTY)
        return FakeResponse(200, text=arxiv_with_summary)

    monkeypatch.setattr(lit_search.requests, "get", fake_get)
    l3_row = make_paper(
        title='Quoted "Method" Analysis',
        abstract=None,
        year=None,
        authors=[],
        externalIds={"DOI": None, "ArXiv": None},
    )
    out = lit_search.enrich_fallback([l3_row])[0]
    assert seen["url"].startswith("https://")
    assert '"' not in seen["params"]["search_query"].replace('ti:"', "").rstrip('"')
    assert out["abstract"] == "We analyze quoted methods empirically."
    assert out["year"] == 2024
    assert out["externalIds"]["ArXiv"] == "2402.09999"
    assert "needs_manual" not in out


def test_queries_from_outline_dedupes_and_ranks(monkeypatch, tmp_path):
    p_a = make_paper(
        paperId="p1",
        title="Graph Neural Networks Survey",
        abstract="graph neural networks",
        externalIds={"DOI": "10.1/p1", "ArXiv": None},
    )
    p_b = make_paper(
        paperId="p2",
        title="Unrelated Storage Paper",
        abstract="disk arrays",
        externalIds={"DOI": "10.1/p2", "ArXiv": None},
    )
    p_a_dup = make_paper(
        paperId="p1",
        title="Graph Neural Networks Survey",
        abstract="",
        externalIds={"DOI": "10.1/p1", "ArXiv": None},
    )

    def fake_get(url, params=None, headers=None, timeout=None):
        q = (params or {}).get("query", "")
        if "graph" in q:
            return FakeResponse(200, {"data": [p_b, p_a]})
        return FakeResponse(200, {"data": [p_a_dup]})

    monkeypatch.setattr(lit_search.requests, "get", fake_get)
    outline = tmp_path / "outline.json"
    outline.write_text(
        json.dumps({
            "title": "T",
            "venue": "V",
            "sections": [],
            "lit_strategy": {"queries": ["graph", "survey"], "must_contain": ["graph neural"]},
            "viz_plan": {"figures": []},
        }),
        encoding="utf-8",
    )
    out = tmp_path / "refs.jsonl"
    lit_search.main([
        "--queries-from", str(outline),
        "--out", str(out),
        "--fallback", "off",
        "--rank",
        "--api-key", "k",
    ])
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 2
    assert rows[0]["paperId"] == "p1"
    assert rows[0]["externalIds"]["DOI"] == "10.1/p1"
    assert rows[0]["abstract"] == "graph neural networks"


def test_existing_bib_and_append_never_drift_existing_citekeys(monkeypatch, tmp_path):
    p1 = make_paper(
        paperId="id1",
        title="Graph Classification",
        authors=["Alice Smith"],
        year=2023,
        externalIds={"DOI": "10.1/id1", "ArXiv": None},
    )
    p2 = make_paper(
        paperId="id2",
        title="Graph Compression",
        authors=["Alice Smith"],
        year=2023,
        externalIds={"DOI": "10.1/id2", "ArXiv": None},
    )
    prev_bib = tmp_path / "prev.bib"
    prev_bib.write_text("@article{smith2023graph,\n  title={{Graph Classification}},\n}\n", encoding="utf-8")

    out = tmp_path / "refs.jsonl"
    out.write_text(json.dumps({**p1, "citekey": "smith2023graph"}) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        lit_search.requests,
        "get",
        lambda url, params=None, headers=None, timeout=None: FakeResponse(200, {"data": [p2]}),
    )
    bib_out = tmp_path / "refs.bib"
    lit_search.main([
        "--query", "graph",
        "--out", str(out),
        "--bib", str(bib_out),
        "--append",
        "--existing-bib", str(prev_bib),
        "--fallback", "off",
        "--api-key", "k",
    ])
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert [r["citekey"] for r in rows] == ["smith2023graph", "smith2023grapha"]


def test_source_crossref_arxiv_and_auto_fallback_on_429(monkeypatch, tmp_path, capsys):
    def fake_get(url, params=None, headers=None, timeout=None):
        if "semanticscholar" in url:
            return FakeResponse(429, {"error": "rate limit"})
        if "crossref" in url:
            return FakeResponse(200, {
                "message": {"items": [{
                    "DOI": "10.1/cr",
                    "title": ["Crossref Paper"],
                    "author": [{"given": "Ada", "family": "Lovelace"}],
                    "issued": {"date-parts": [[2023]]},
                    "container-title": ["ICLR"],
                }]}
            })
        if "arxiv" in url:
            return FakeResponse(200, text=(
                '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
                "<entry><id>https://arxiv.org/abs/2301.00001v1</id>"
                "<title>ArXiv Paper</title><summary>Abs.</summary>"
                "<published>2023-01-01T00:00:00Z</published>"
                "<author><name>Alan Turing</name></author></entry></feed>"
            ))
        raise AssertionError(url)

    monkeypatch.setattr(lit_search.requests, "get", fake_get)
    monkeypatch.setattr(lit_search.time, "sleep", lambda s: None)

    out_auto = tmp_path / "auto.jsonl"
    lit_search.main(["--query", "test", "--out", str(out_auto), "--source", "auto", "--fallback", "off"])
    err = capsys.readouterr().err
    assert "auto" in err
    rows = [json.loads(l) for l in out_auto.read_text(encoding="utf-8").splitlines() if l.strip()]
    titles = {r["title"] for r in rows}
    assert {"Crossref Paper", "ArXiv Paper"} <= titles


def test_emit_ledger_draft_and_numeric_map_integrate_with_scripts(monkeypatch, tmp_path):
    import latex_compose
    import ledger_audit

    p_l2 = make_paper(
        paperId="p2",
        title="With Abstract",
        abstract="Good summary.",
        authors=["Ada Lovelace"],
        year=2024,
        externalIds={"DOI": "10.1/l2", "ArXiv": None},
    )
    p_l3 = make_paper(
        paperId="p3",
        title="Title Only",
        abstract=None,
        authors=["Grace Hopper"],
        year=2023,
        externalIds={"DOI": "10.1/l3", "ArXiv": None},
    )
    monkeypatch.setattr(
        lit_search.requests,
        "get",
        lambda url, params=None, headers=None, timeout=None: FakeResponse(200, {"data": [p_l2, p_l3]}),
    )
    out = tmp_path / "refs.jsonl"
    bib = tmp_path / "refs.bib"
    draft = tmp_path / "claims_refs.jsonl"
    nmap = tmp_path / "numeric_map.json"
    lit_search.main([
        "--query", "compilers",
        "--out", str(out),
        "--bib", str(bib),
        "--fallback", "off",
        "--emit-ledger-draft", str(draft),
        "--emit-numeric-map", str(nmap),
        "--api-key", "k",
    ])
    mat = tmp_path / "materials"
    mat.mkdir()
    assert ledger_audit.audit_claims(draft, mat) == []
    claims = ledger_audit.load_claims(draft)
    assert [c["evidence_level"] for c in claims] == ["L2", "L3"]
    loaded_map = json.loads(nmap.read_text(encoding="utf-8"))
    bridged = latex_compose.to_cites("Prior work [1,2] exists.", loaded_map)
    assert r"\cite{lovelace2024abstract,hopper2023title}" in bridged


def test_l3_tldr_suppressed_by_default_and_kept_with_flag(monkeypatch, tmp_path):
    p_l3 = make_paper(paperId="p3", title="Title Only", abstract=None, tldr="AI summary text")
    monkeypatch.setattr(
        lit_search.requests,
        "get",
        lambda url, params=None, headers=None, timeout=None: FakeResponse(200, {"data": [p_l3]}),
    )
    out_default = tmp_path / "default.jsonl"
    lit_search.main(["--query", "q", "--out", str(out_default), "--fallback", "off", "--api-key", "k"])
    row1 = json.loads(out_default.read_text(encoding="utf-8").splitlines()[0])
    assert row1["tldr"] is None

    out_keep = tmp_path / "keep.jsonl"
    lit_search.main([
        "--query", "q", "--out", str(out_keep), "--fallback", "off",
        "--keep-l3-tldr", "--api-key", "k",
    ])
    row2 = json.loads(out_keep.read_text(encoding="utf-8").splitlines()[0])
    assert row2["tldr"] == "AI summary text"
