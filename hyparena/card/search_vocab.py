"""Vocabulary guard for model-written PubMed queries (calibration, 2026-11-02).

A model composes the queries of a claim (which concepts, which synonyms, how to combine them); it may not add words of its own.
Every term of a query must come from the card's own text, from the MeSH entry terms of a MeSH descriptor found by a card phrase
(NCBI, free), from the synonyms of the card's compounds (PubChem via hyparena.tools.compounds), or from a short fixed list of
generic words (study design, ageing outcomes, organisms). Terms outside it are dropped and logged; a concept group left empty is
dropped, so the query becomes broader, never different in topic. The query is re-serialised by code (brackets included).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "mesh_terms.json"
GENERIC = {
    "randomized", "randomised", "controlled", "trial", "trials", "clinical", "study", "studies", "effect", "effects", "intervention",
    "interventions", "placebo", "supplementation", "supplement", "treatment", "therapy", "older", "old", "elderly", "aged", "aging",
    "ageing", "adults", "adult", "people", "persons", "humans", "human", "men", "women", "lifespan", "life", "span", "longevity",
    "survival", "mortality", "healthspan", "physical", "function", "functional", "performance", "mice", "mouse", "murine", "rats",
    "rat", "rodent", "rodents", "worm", "worms", "nematode", "nematodes", "caenorhabditis", "elegans", "drosophila", "melanogaster",
    "fly", "flies", "fruit", "yeast", "saccharomyces", "cerevisiae", "expectancy", "median", "maximum", "chronological", "replicative",
}
STOP = {"of", "the", "a", "an", "in", "on", "and", "or", "for", "with", "to", "by", "at", "as", "vs", "versus"}
TAG = re.compile(r"\[[^\]]+\]")
TOKEN = re.compile(r'\(|\)|"[^"]*"(?:\[[^\]]+\])?|\bAND\b|\bOR\b|\bNOT\b|[^\s()"]+(?:\[[^\]]+\])?')


def _words(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9\-']*", (s or "").lower()) if w not in STOP]


def _load() -> dict:
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def mesh_terms(phrase: str, cache: Optional[dict] = None) -> list[str]:
    """Entry terms of up to 3 MeSH descriptors found by the phrase (cached)."""
    import httpx
    cache = cache if cache is not None else _load()
    key = phrase.lower().strip()
    if key in cache:
        return cache[key]
    terms: list[str] = []
    for attempt in range(3):
        try:
            ids = httpx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                            params={"db": "mesh", "term": key, "retmode": "json", "retmax": 3}, timeout=30).json()["esearchresult"]["idlist"]
            if ids:
                time.sleep(0.4)
                res = httpx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                                params={"db": "mesh", "id": ",".join(ids), "retmode": "json"}, timeout=30).json()["result"]
                terms = [t for u in res.get("uids", []) for t in (res[u].get("ds_meshterms") or [])]
            break
        except Exception:
            time.sleep(2 ** attempt)
    cache[key] = terms
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache))
    time.sleep(0.4)
    return terms


def card_phrases(card) -> list[str]:
    """The card phrases that name concepts: intervention, population, outcome, claim subjects and objects."""
    p = card.pico
    out = [i.label for i in p.intervention] + [p.population.label, p.outcome.metric or "", p.comparator.label or ""]
    for c in card.claims:
        out += [c.subject.label, c.object.label, c.qualifiers.get("measure", "")]
    return [x for x in dict.fromkeys(o.strip() for o in out if o and o.strip() and o.lower() != "unknown")]


def vocabulary(card) -> dict:
    """{'words': set of allowed words, 'phrases': set of allowed phrases, 'sources': counts}."""
    from hyparena.tools import compounds as cp
    text = json.dumps(card.model_dump(by_alias=True), ensure_ascii=False)
    words = set(_words(text)) | GENERIC
    phrases: set[str] = set()
    cache = _load()
    mesh = 0
    for ph in card_phrases(card):
        for t in mesh_terms(ph, cache):
            phrases.add(t.lower())
            words |= set(_words(t))
            mesh += 1
    syn = 0
    for i in card.pico.intervention:
        if i.type == "compound":
            comp = cp.lookup(i.label)
            for s in (getattr(comp, "synonyms", None) or [])[:50]:
                phrases.add(s.lower())
                words |= set(_words(s))
                syn += 1
    return {"words": words, "phrases": phrases, "sources": {"mesh_terms": mesh, "compound_synonyms": syn}}


def term_allowed(term: str, vocab: dict) -> bool:
    if re.search(r"\[(pt|publication type)\]", term, re.I):
        return True                                      # publication type filters carry no topic
    t = TAG.sub("", term).strip().strip('"').lower()
    if not t or t in vocab["phrases"]:
        return True
    ws = _words(t.replace("*", ""))
    for w in ws:
        if w in vocab["words"] or w.rstrip("s") in vocab["words"] or w + "s" in vocab["words"]:
            continue
        if term.rstrip("]").find("*") >= 0 and any(v.startswith(w) for v in vocab["words"]):
            continue
        return False
    return True


def _parse(tokens: list[str], i: int = 0):
    """[items...] where items are terms, operators or nested lists; returns (list, next index)."""
    out = []
    while i < len(tokens):
        t = tokens[i]
        if t == "(":
            sub, i = _parse(tokens, i + 1)
            out.append(sub)
        elif t == ")":
            return out, i + 1
        else:
            out.append(t)
            i += 1
    return out, i


def _filter(node, vocab: dict, dropped: list):
    if isinstance(node, str):
        if node in ("AND", "OR", "NOT"):
            return node
        if term_allowed(node, vocab):
            return node
        dropped.append(node)
        return None
    items = [_filter(x, vocab, dropped) for x in node]
    # remove dropped operands with their operator, keep the operator structure valid
    clean = []
    for x in items:
        if x is None or x == []:
            if clean and clean[-1] in ("AND", "OR", "NOT"):
                clean.pop()
            continue
        if x in ("AND", "OR", "NOT") and (not clean or clean[-1] in ("AND", "OR", "NOT")):
            continue
        clean.append(x)
    while clean and clean[-1] in ("AND", "OR", "NOT"):
        clean.pop()
    # implicit AND between adjacent operands (PubMed's default)
    return clean


def _serialise(node) -> str:
    if isinstance(node, str):
        return node
    parts = [_serialise(x) for x in node]
    return " ".join(parts)


def _wrap(node) -> str:
    if isinstance(node, str):
        return node
    inner = " ".join(_wrap(x) for x in node)
    return f"({inner})" if len(node) > 1 else inner


def _merge(tokens: list[str]) -> list[str]:
    """Adjacent words that are not operators or brackets form one term ("insulin-like growth factor[tiab]")."""
    out: list[str] = []
    for t in tokens:
        plain = t not in ("(", ")", "AND", "OR", "NOT")
        if plain and out and out[-1] not in ("(", ")", "AND", "OR", "NOT") and not out[-1].endswith("]"):
            out[-1] = out[-1] + " " + t
        else:
            out.append(t)
    return out


def filter_query(q: str, vocab: dict) -> tuple[str, list[str]]:
    """The query with every term outside the vocabulary removed, re-serialised with brackets; and the dropped terms."""
    tokens = _merge(TOKEN.findall(q))
    tree, _ = _parse(tokens)
    dropped: list[str] = []
    clean = _filter(tree, vocab, dropped)
    return " ".join(_wrap(x) for x in clean).strip(), dropped
