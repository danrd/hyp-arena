"""Can an ontology set the link type better than the model? A free check on Argon pack 17 (PubMed E-utilities only).

    python -m scripts.link_ontology_check    # longevity-kg/reviews/argon-2026-11-12/link_ontology_check.json

On the claim pairs where our card (normaliser v13, deduplicated) and the outside reader's gold match by phrase, the link type
is set three ways and compared with the gold (Cohen's kappa, per gold class):
  llm       the normaliser's own link (none = off the chain);
  premise   the rule of docs/system/card.md only: a claim whose subject is neither the intervention nor an object of an earlier
            claim is a premise (off the chain); otherwise the normaliser's link;
  ontology  the rules plus the level from MeSH: outcome stays outcome (its role); premise as above; else the object (the
            measure where the object is the organism) is mapped to MeSH by PubMed's own term mapping, its head term (the last
            mapped one) gives the level by tree - chemicals D: molecule; cell structures A11 and cell, genetic and metabolic
            phenomena G02-G05: cell; anatomy A01-A10, A12-A16, physiology G06-G12: tissue or organ; diseases C, behaviour F,
            care and outcomes N, E01: organism - and the level gives the link: molecule -> engagement when the subject is the
            intervention, else pathway; cell -> pathway; tissue or organ -> effect; organism -> outcome; unmapped -> the
            normaliser's link.
Gold labels: population_state and none are both "premise" (off the chain).
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

from scripts import bench_card as b

DIR = b.DIR
CACHE = DIR / "link_ontology_cache.json"
EU = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
POP = {"aged", "humans", "adult", "middle aged", "aged, 80 and over", "male", "female", "mice", "rats", "animals", "frail elderly",
       "young adult", "adolescent", "child", "infant", "patients", "persons", "population"}
STOP = r"\b(older|elderly|adults?|people|participants|patients|in|of|the|and|aged|humans?|mice|years?)\b"
_last = [0.0]


def _get(path: str, params: dict) -> dict:
    for attempt in range(5):
        wait = 0.36 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            return json.loads(urllib.request.urlopen(EU + path + "?" + urllib.parse.urlencode(params), timeout=60).read())
        except Exception:
            time.sleep(2 ** attempt)
    raise RuntimeError(path)


def _mesh_terms(text: str, cache: dict) -> list[str]:
    k = "t|" + text
    if k not in cache:
        r = _get("esearch.fcgi", {"db": "pubmed", "term": text, "retmax": 0, "retmode": "json"})["esearchresult"]
        terms = []
        for t in r.get("translationset", []):
            terms += [m for m in re.findall(r'"([^"]+)"\[MeSH Terms\]', t.get("to", ""))]
        cache[k] = terms
    return cache[k]


def _trees(term: str, cache: dict) -> list[str]:
    k = "m|" + term
    if k not in cache:
        ids = _get("esearch.fcgi", {"db": "mesh", "term": f'"{term}"[mh]', "retmode": "json"})["esearchresult"].get("idlist", [])
        tr = []
        if ids:
            res = _get("esummary.fcgi", {"db": "mesh", "id": ids[0], "retmode": "json"})["result"].get(ids[0], {})
            tr = [x.get("treenum", "") for x in res.get("ds_idxlinks", []) if x.get("treenum")]
        cache[k] = tr
    return cache[k]


def level_of(tree: str) -> str | None:
    if tree.startswith("D"):
        return "molecule"
    if tree.startswith("A11") or tree[:3] in ("G02", "G03", "G04", "G05"):
        return "cell"
    if tree[:1] == "A" or tree[:3] in ("G06", "G07", "G08", "G09", "G10", "G11", "G12"):
        return "tissue_organ"
    if tree[:1] in ("C", "F", "N") or tree.startswith("E01"):
        return "organism"
    return None


def head_level(text: str, cache: dict) -> tuple[str | None, str | None]:
    text = re.sub(STOP, " ", (text or "").lower())
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None, None
    for term in reversed(_mesh_terms(text, cache)):
        if term.lower() in POP:
            continue
        for tr in _trees(term, cache):
            lv = level_of(tr)
            if lv:
                return lv, term
    return None, None


def _toks(s: str) -> set:
    return set(re.findall(r"[a-z0-9]{3,}", (s or "").lower())) - {"the", "and", "with", "older", "adults", "elderly"}


def run() -> dict:
    ans = {i["id"]: i for i in json.loads((DIR / "pack_17_answer.json").read_text())["items"]}
    ours = json.loads((DIR / "bench_card_ours_v13_dedup.json").read_text())
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    rows = []
    try:
        for k, a in ans.items():
            card = ours.get(k, {}).get("card")
            if not card:
                continue
            raw = card.get("claims") or []
            sysc = [{"phrase": c.get("source_span") or "", "link": c.get("link") or "none", "raw": c} for c in raw]
            itoks = set().union(*[_toks(i.get("label")) for i in card["pico"].get("intervention") or []] or [set()])
            for s_, g in b._match(sysc, a["claims"]):
                c = s_["raw"]
                idx = raw.index(c)
                earlier = set().union(*[_toks(x["object"]["label"]) | _toks((x.get("qualifiers") or {}).get("measure"))
                                        for x in raw[:idx]] or [set()])
                stoks = _toks(c["subject"]["label"])
                on_chain = bool(stoks & itoks) or bool(stoks & earlier)
                llm = c.get("link") or "none"
                llm = "premise" if llm == "none" else llm
                prem = llm if (on_chain or llm == "outcome") else "premise"
                if llm == "outcome":
                    ont, lv, term = "outcome", None, None
                elif not on_chain:
                    ont, lv, term = "premise", None, None
                else:
                    obj = c["object"]["label"]
                    if c.get("relation", "").endswith("_in") or (c["object"].get("id") or "").startswith("NCBITaxon"):
                        obj = (c.get("qualifiers") or {}).get("measure") or obj
                    lv, term = head_level(obj, cache)
                    ont = {"molecule": "engagement" if stoks & itoks else "pathway", "cell": "pathway", "tissue_organ": "effect",
                           "organism": "outcome"}.get(lv, llm)
                gold = g.get("link") or "none"
                gold = "premise" if gold in ("none", "population_state") else gold
                rows.append({"text": k, "gold": gold, "llm": llm, "premise": prem, "ontology": ont, "level": lv, "mesh": term,
                             "subject": c["subject"]["label"], "object": c["object"]["label"], "on_chain": on_chain})
    finally:
        CACHE.write_text(json.dumps(cache) + "\n")
    out = {"pairs": len(rows), "mapped": sum(r["level"] is not None for r in rows),
           "steps_to_map": sum(r["llm"] != "outcome" and r["on_chain"] for r in rows)}
    for v in ("llm", "premise", "ontology"):
        out[v] = {"kappa": b._kappa([(r["gold"], r[v]) for r in rows]),
                  "agree": round(sum(r["gold"] == r[v] for r in rows) / len(rows), 3),
                  "by_gold": {gl: f"{sum(r[v] == gl for r in rows if r['gold'] == gl)}/{sum(r['gold'] == gl for r in rows)}"
                              for gl in ("engagement", "pathway", "effect", "outcome", "premise", "delivery")}}
        nonout = [r for r in rows if r["gold"] != "outcome"]
        out[v]["kappa_without_outcome"] = b._kappa([(r["gold"], r[v]) for r in nonout])
    (DIR / "link_ontology_check.json").write_text(json.dumps({"summary": out, "rows": rows}, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=1, ensure_ascii=False))
