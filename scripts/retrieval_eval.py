"""How well does the verifier's literature search find what it should? (calibration, 2026-11-02)

    python -m scripts.retrieval_eval build                 # 24 human trials + 24 animal claims, gold PMIDs; human texts only
    ALLOW_PAID=1 python -m scripts.retrieval_eval cards    # cards of the human trials (normalizer, configs/v2-flash.yaml)
    ALLOW_PAID=1 python -m scripts.retrieval_eval queries  # queries written by a model (DeepSeek, one call per claim)
    python -m scripts.retrieval_eval eval                  # recall@20 of the gold per strategy, free (PubMed, NCBI links)

Gold, both free and outside the benchmark:
- humans: CT.gov trials outside the benchmark; the BACKGROUND references the investigators listed in the registry, published on or
  before the registration date (the literature the trial stood on). Not all of them must be found (some are general reviews):
  the measure compares strategies, it is not an absolute recall.
- animals and compounds: "X extends the lifespan of species S" as of the first DrugAge paper on (X, S); the gold is the DrugAge
  papers on X in other species published before that date.
Strategies: S0 the current queries (hyparena.card.verifier.queries); S1 queries written by a model; S2 = S1 plus the references
and citing papers of its top hits (NCBI elink), dated by the guard; S3 the knowledge graph (longevity-kg extracted rows) for the
animal claims. S3 is partly circular here: the graph's first corpus was built from DrugAge papers.
Each strategy returns at most 20 PMIDs dated on or before T, the number the verifier reads.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from scripts.benchmark_run import build_texts
from scripts.ctgov_outcomes import KG

OUT = KG / "hypothesis_sources" / "calibration" / "retrieval"
SCRATCH_REFS = Path(os.environ.get("REFS_JSON", ""))     # optional cache of CT.gov references (scratch)
N = 20
SPECIES = {"mouse": "Mus musculus", "worm": "Caenorhabditis elegans", "fly": "Drosophila melanogaster"}
QUERY_PROMPT = """You search PubMed for the evidence that existed on {as_of} about one research claim. Write 4 different PubMed
queries that a systematic reviewer would use to find primary studies testing this claim or the same intervention on the same
kind of outcome. Use synonyms, MeSH terms ([MeSH]) and title/abstract fields ([tiab]) where useful, brackets around OR groups.
Do not name studies, trials or results you know of; only describe the topic.

Claim: {claim}
Intervention: {intervention}
Population: {population}
Outcome: {outcome}

Reply with a JSON object only: {{"queries": ["...", "...", "...", "..."]}}"""


def _h(x: str) -> str:
    return hashlib.sha1(x.encode()).hexdigest()


def _type(c: dict) -> str:
    t = {i.get("type") for i in c.get("interventions") or []}
    return ("drug" if t & {"DRUG", "DIETARY_SUPPLEMENT", "BIOLOGICAL"} else "behavioral" if "BEHAVIORAL" in t
            else "device" if "DEVICE" in t else "other")


def _refs(nct: str) -> list[dict]:
    import httpx
    p = httpx.get(f"https://clinicaltrials.gov/api/v2/studies/{nct}?fields=protocolSection.referencesModule", timeout=60).json()
    return [{"pmid": r["pmid"], "type": r.get("type")} for r in
            ((p.get("protocolSection") or {}).get("referencesModule") or {}).get("references", []) if r.get("pmid")]


def build() -> dict:
    from hyparena.backtest import _pubdates, drugage_rows
    bench = {u["id"] for u in json.loads((Path(__file__).resolve().parents[1] / "data/benchmark/v2_units.json").read_text())["units"]}
    cands = {c["source_id"]: c for c in yaml.safe_load((KG / "hypothesis_sources/ctgov_candidates.yaml").read_text())["items"]}
    cache = json.loads(SCRATCH_REFS.read_text()) if SCRATCH_REFS.is_file() else {}
    by_type = defaultdict(list)
    for nct in sorted((n for n in cands if n not in bench), key=_h):
        by_type[_type(cands[nct])].append(nct)
    human = []
    for t, want in (("drug", 6), ("other", 6), ("behavioral", 6), ("device", 6)):
        for nct in by_type[t]:
            if sum(1 for h in human if h["type"] == t) >= want:
                break
            refs = cache.get(nct) if nct in cache else _refs(nct)
            bg = [r["pmid"] for r in refs if r["type"] == "BACKGROUND"]
            d = _pubdates(bg) if bg else {}
            gold = [p for p in bg if p in d and d[p] <= cands[nct]["written_on"]]
            if gold:
                human.append({"id": nct, "type": t, "as_of": cands[nct]["written_on"], "gold": gold})
    OUT.mkdir(parents=True, exist_ok=True)
    build_texts([{"id": h["id"], "source": "ctgov", "written_on": h["as_of"]} for h in human], OUT / "human_texts.jsonl")
    # animals: first DrugAge paper on (compound, species); gold = earlier DrugAge papers on the compound in other species
    rows = drugage_rows()
    pm = sorted({r["pubmed_id"] for r in rows if r["pubmed_id"]})
    dates = _pubdates(pm)
    first = {}
    for r in rows:
        p = r["pubmed_id"]
        if p in dates:
            k = (r["compound_name"], r["species"])
            first[k] = min(first.get(k, "9999"), dates[p])
    papers = defaultdict(set)
    for r in rows:
        if r["pubmed_id"] in dates:
            papers[(r["compound_name"], r["species"])].add(r["pubmed_id"])
    animal = []
    groups = [("mouse", ["Mus musculus"]), ("worm", ["Caenorhabditis elegans"]), ("fly", ["Drosophila melanogaster"]),
              ("other", ["Rattus norvegicus", "Saccharomyces cerevisiae"])]
    for name, sp in groups:
        ks = sorted((k for k in first if k[1] in sp), key=lambda k: _h("|".join(k)))
        for comp, s in ks:
            T = first[(comp, s)]
            gold = sorted({p for (c2, s2), ps in papers.items() if c2 == comp and s2 != s for p in ps if dates[p] < T})
            if gold:
                animal.append({"id": f"{comp}|{s}", "type": name, "compound": comp, "species": s, "as_of": T, "gold": gold})
            if sum(1 for a in animal if a["type"] == name) >= 6:
                break
    (OUT / "set.json").write_text(json.dumps({"human": human, "animal": animal}, indent=1) + "\n")
    return {"human": Counter(h["type"] for h in human), "animal": Counter(a["type"] for a in animal),
            "gold_per_claim_human": sorted(len(h["gold"]) for h in human), "gold_per_claim_animal": sorted(len(a["gold"]) for a in animal)}


def animal_card(a: dict):
    from hyparena.card.models import HypothesisCard
    sp = a["species"]
    taxon = {"Mus musculus": "NCBITaxon:10090", "Caenorhabditis elegans": "NCBITaxon:6239", "Drosophila melanogaster": "NCBITaxon:7227",
             "Rattus norvegicus": "NCBITaxon:10116", "Saccharomyces cerevisiae": "NCBITaxon:4932"}.get(sp)
    obj = {"Mus musculus": "mouse", "Caenorhabditis elegans": "nematode", "Drosophila melanogaster": "fly",
           "Rattus norvegicus": "rat", "Saccharomyces cerevisiae": "yeast"}.get(sp, sp)
    return HypothesisCard.model_validate({
        "id": "H-0001", "raw_id": "H-0001", "hypothesis_type": "interventional",
        "claim_plain": f"{a['compound']} extends the lifespan of {sp}.",
        "pico": {"population": {"taxon": taxon, "label": sp, "strain": "unknown", "sex": "unknown", "age_at_start": "unknown"},
                 "intervention": [{"type": "compound", "label": a["compound"], "id": None, "regimen": "unknown", "route": "unknown"}],
                 "comparator": {"type": "control", "label": "untreated control"}, "outcome": {"endpoint": "lifespan", "metric": "median lifespan"},
                 "time": "unknown"},
        "claims": [{"id": "c1", "subject": {"label": a["compound"]}, "relation": "extends_lifespan_in", "object": {"label": obj},
                    "qualifiers": {"species": obj}, "role": "outcome", "source_span": f"{a['compound']} extends the lifespan of {sp}."}],
        "decisive_experiment": {"system": {"nematode": "worm"}.get(obj, obj) if obj in ("mouse", "nematode", "fly", "rat", "yeast") else "unknown",
                                "endpoint": "lifespan", "duration_class": "months"}})


def claims() -> list[tuple[dict, object, object]]:
    """(item, card, main claim) for every item with a card."""
    from hyparena.card.models import HypothesisCard
    s = json.loads((OUT / "set.json").read_text())
    cards = json.loads((OUT / "human_cards.json").read_text()) if (OUT / "human_cards.json").exists() else {}
    out = []
    for h in s["human"]:
        if cards.get(h["id"]):
            card = HypothesisCard.model_validate(cards[h["id"]])
            out.append((h, card, card.outcome_claim or card.claims[0]))
    for a in s["animal"]:
        card = animal_card(a)
        out.append((a, card, card.claims[0]))
    return out


def make_cards() -> None:
    from hyparena.card.normalizer import normalize
    from hyparena.card.pipeline import _client
    texts = [json.loads(l) for l in (OUT / "human_texts.jsonl").read_text().splitlines()]
    client, fams = _client("configs/v2-flash.yaml", False, 4 * len(texts))
    p = OUT / "human_cards.json"
    cards = json.loads(p.read_text()) if p.exists() else {}
    for t in texts:
        if t["id"] in cards:
            continue
        card, problems = normalize(client, "google", t["text"], "H-0001")
        cards[t["id"]] = card.model_dump(by_alias=True) if card else None
        p.write_text(json.dumps(cards, ensure_ascii=False, indent=1))
        print(t["id"], bool(card), problems[:1], flush=True)


def make_queries() -> None:
    from hyparena.card.pipeline import _client
    from hyparena.card.llm import parse_objects
    client, _ = _client("configs/v2-flash.yaml", False, 200)
    p = OUT / "llm_queries.json"
    done = json.loads(p.read_text()) if p.exists() else {}
    for item, card, c in claims():
        if item["id"] in done:
            continue
        pico = card.pico
        prompt = QUERY_PROMPT.format(as_of=item["as_of"], claim=card.claim_plain,
                                     intervention="; ".join(i.label for i in pico.intervention) or c.subject.label,
                                     population=pico.population.label, outcome=(pico.outcome.metric or c.object.label))
        r = client.call(role="search_queries", family="deepseek", prompt=prompt)
        obj = next((o for o in parse_objects(r.text) if isinstance(o.get("queries"), list)), {"queries": []})
        done[item["id"]] = {"queries": obj["queries"][:4], "tokens_in": r.tokens_in, "tokens_out": r.tokens_out}
        p.write_text(json.dumps(done, ensure_ascii=False, indent=1))
        print(item["id"], obj["queries"][:2], flush=True)


def _dated(pmids: list[str], as_of: str) -> list[str]:
    from hyparena.backtest import _pubdates
    d = _pubdates(pmids) if pmids else {}
    return [p for p in pmids if p in d and d[p] <= as_of]


def run_queries(qs: list[str], as_of: str) -> list[str]:
    from hyparena.tools import pubmed
    found: list[str] = []
    for q in qs:
        found += [p for p in pubmed.search(q, retmax=N, as_of=as_of) if p not in found]
        if len(found) >= N:
            break
    return _dated(found, as_of)[:N]


def round_robin(qs: list[str], as_of: str) -> list[str]:
    """One list per query, merged in turn: every query gets its best hits in."""
    from hyparena.tools import pubmed
    lists = [pubmed.search(q, retmax=N, as_of=as_of) for q in qs]
    out: list[str] = []
    for i in range(N):
        for lst in lists:
            if i < len(lst) and lst[i] not in out:
                out.append(lst[i])
    return _dated(out, as_of)[:N]


def citation_expand(seed: list[str], as_of: str, top: int = 5, keep: int = 10) -> list[str]:
    """The first `keep` seeds, then the papers most often linked (references or citing) from the top `top` seeds, dated by T."""
    import httpx
    count: Counter = Counter()
    for p in seed[:top]:
        for link in ("pubmed_pubmed_refs", "pubmed_pubmed_citedin"):
            try:
                r = httpx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi",
                              params={"dbfrom": "pubmed", "db": "pubmed", "id": p, "linkname": link, "retmode": "json"}, timeout=60).json()
                ids = [x for ls in r.get("linksets", []) for db in ls.get("linksetdbs", []) for x in db.get("links", [])]
            except Exception:
                ids = []
            count.update(str(x) for x in ids)
    extra = _dated([p for p, _ in count.most_common(60) if p not in seed], as_of)
    return (seed[:keep] + extra)[:N]


def kg_lookup(item: dict) -> list[str]:
    if "compound" not in item:
        return []
    name = item["compound"].lower()
    pm = []
    for f in glob.glob(str(KG / "extracted" / "*.jsonl")):
        for line in open(f):
            if name in line.lower():
                r = json.loads(line)
                if (r.get("intervention") or {}).get("label", "").lower() == name:
                    pm.append(r["pmid"])
    return _dated(list(dict.fromkeys(pm)), item["as_of"])[:N]


def evaluate() -> dict:
    from hyparena.card.verifier import queries
    llm = json.loads((OUT / "llm_queries.json").read_text()) if (OUT / "llm_queries.json").exists() else {}
    per = []
    for item, card, c in claims():
        g = set(item["gold"])
        s0 = run_queries(queries(c, card), item["as_of"])
        res = {"S0": s0}
        if item["id"] in llm and llm[item["id"]]["queries"]:
            s1 = round_robin(llm[item["id"]]["queries"], item["as_of"])
            res["S1"] = s1
            res["S1+S2"] = citation_expand(s1, item["as_of"])
        res["S0+S2"] = citation_expand(s0, item["as_of"])
        if "compound" in item:
            res["S3 (circular)"] = kg_lookup(item)
        row = {"id": item["id"], "group": ("human " if "compound" not in item else "animal ") + item["type"], "gold": len(g)}
        for k, v in res.items():
            row[k] = {"found": len(v), "gold_hit": len(g & set(v)), "recall": round(len(g & set(v)) / len(g), 2)}
        per.append(row)
        print(json.dumps({k: (v if not isinstance(v, dict) else v["gold_hit"]) for k, v in row.items()}), flush=True)
    summary = defaultdict(lambda: defaultdict(list))
    for r in per:
        for k, v in r.items():
            if isinstance(v, dict):
                for grp in (r["group"].split()[0], "all"):
                    summary[grp][k].append(v)
    table = {grp: {k: {"mean_recall": round(sum(x["recall"] for x in v) / len(v), 3),
                       "any_hit": round(sum(x["gold_hit"] > 0 for x in v) / len(v), 2), "n": len(v)} for k, v in d.items()}
             for grp, d in summary.items()}
    (OUT / "eval.json").write_text(json.dumps({"per_claim": per, "summary": table}, indent=1) + "\n")
    return table


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["build", "cards", "queries", "eval", "relevance"])
    a = ap.parse_args()
    if a.cmd in ("cards", "queries") and os.environ.get("ALLOW_PAID") != "1":
        raise SystemExit("paid: set ALLOW_PAID=1")
    if a.cmd == "build":
        print(json.dumps(build(), indent=1, default=str))
    elif a.cmd == "cards":
        make_cards()
    elif a.cmd == "queries":
        make_queries()
    elif a.cmd == "relevance":
        print(relevance_task())
    else:
        print(json.dumps(evaluate(), indent=1))



def relevance_task(per_group: int = 2) -> dict:
    """Blind relevance labelling (Jules): for 2 claims per group, the union of the S0 and S1+S2 lists with abstracts, shuffled,
    without the strategy names. Written to $KG_DIR (abstracts belong to their publishers)."""
    import random
    from hyparena.card.verifier import queries
    from hyparena.tools import pubmed
    llm = json.loads((OUT / "llm_queries.json").read_text())
    groups = defaultdict(list)
    for item, card, c in claims():
        groups[("human " if "compound" not in item else "animal ") + item["type"]].append((item, card, c))
    task, key = [], {}
    for g, xs in sorted(groups.items()):
        for item, card, c in sorted(xs, key=lambda x: _h(x[0]["id"]))[:per_group]:
            s0 = run_queries(queries(c, card), item["as_of"])
            s12 = citation_expand(round_robin(llm[item["id"]]["queries"], item["as_of"]), item["as_of"])
            union = list(dict.fromkeys(s0 + s12))
            random.Random(_h(item["id"])).shuffle(union)
            abs_ = pubmed.fetch(union)
            task.append({"claim_id": item["id"], "group": g, "as_of": item["as_of"], "claim": card.claim_plain,
                         "intervention": "; ".join(i.label for i in card.pico.intervention), "population": card.pico.population.label,
                         "papers": [{"pmid": p, "title": abs_.get(p, {}).get("title", ""), "abstract": abs_.get(p, {}).get("abstract", "")}
                                    for p in union]})
            key[item["id"]] = {"S0": s0, "S1+S2": s12}
    d = OUT / "relevance"
    d.mkdir(exist_ok=True)
    (d / "task.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in task))
    (d / "strategy_key.json").write_text(json.dumps(key, indent=1) + "\n")
    return {"claims": len(task), "pairs": sum(len(t["papers"]) for t in task)}


if __name__ == "__main__":
    main()
