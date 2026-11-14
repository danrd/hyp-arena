"""Literature search of one claim with model-written queries (calibration 2026-11-02, configs with `search: model`).

1. A model writes 4 PubMed queries (prompt search_queries/v1): concepts, synonyms, MeSH, brackets.
2. The light guard (hyparena.card.search_vocab, user decision 2026-11-02) drops direction words absent from the card, study
   acronyms, registry numbers and author searches; dropped terms are logged.
3. The queries run as of T and their lists are merged in turn (each query gets its best hits in).
4. Citation expansion: the references and citing papers of the top 5 hits (NCBI elink), most frequent first, dated by T.
5. The keyword queries of hyparena.card.verifier.queries fill up to `retmax` if fewer were found.
Retrieval calibration (scripts/retrieval_eval.py): at least one gold paper among the 20 read for 38% of 48 claims, against 12%
for the keyword queries; relevance labels on 16 claims: 3.8 directly relevant papers per claim against 1.9.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

TOP_SEEDS, KEEP_SEEDS = 5, 10
PER_QUERY, LINKED_MAX, RATED, FILL, CAP = 200, 600, 100, 10, 20      # search mode "filtered" (retrieve_filtered)
FILTER_FAMILY, FILTER_BATCH, FILTER_ABSTRACT = "deepseek", 20, 900
ALTERNATIVE_NOTE = "proposed alternative"   # set by the pipeline on the claim made from a proposed alternative


def _dated(pmids: list[str], as_of: Optional[str]) -> list[str]:
    if not as_of or not pmids:
        return list(pmids)
    from hyparena import backtest
    d = backtest._pubdates(pmids)
    return [p for p in pmids if p in d and d[p] <= as_of]


ORGANISM_RELATIONS = ("improves_healthspan_in", "extends_lifespan_in", "shortens_lifespan_in", "slows_aging_in",
                      "no_lifespan_effect_in")


def _synonyms(card, claim) -> str:
    """MeSH headings and entry terms of the card's entities this claim names (intervention, population, its outcome)."""
    if not getattr(card, "identifiers", None):
        return ""
    from hyparena.tools import mesh
    names = [i.label for i in card.pico.intervention] + [card.pico.population.who, link_outcome(claim), claim.object.label]
    lines = []
    for lab in dict.fromkeys(n for n in names if n in card.identifiers):
        syn = mesh.synonyms(lab)
        if syn:
            lines.append(f"{lab}: " + "; ".join(syn) + f" (MeSH heading: {card.identifiers[lab]['name']})")
    return "\n".join(lines)


def link_outcome(claim) -> str:
    """The outcome line of the query prompt is the link's own object (its measure where the object is the organism), not all
    outcomes of the trial (user decision 2026-11-11: on H49 the body-composition link got queries about SPPB)."""
    if claim.relation in ORGANISM_RELATIONS:
        m = claim.qualifiers.get("measure", "")
        return m if m and m != "unknown" else claim.relation.replace("_in", "").replace("_", " ")
    return claim.object.label


def model_queries(client, family: str, avoid, claim, card, as_of: Optional[str], log: Optional[list] = None) -> list[str]:
    from hyparena.card.llm import ask
    from hyparena.card.search_vocab import filter_query, vocabulary
    p = card.pico
    variables = {"as_of": as_of or "today", "claim_plain": card.claim_plain, "claim": claim,
                 "qualifiers": ", ".join(f"{k}: {v}" for k, v in claim.qualifiers.items() if v and v != "unknown"),
                 "intervention": "; ".join(i.label for i in p.intervention) or claim.subject.label,
                 "population": p.population.who, "outcome": link_outcome(claim), "synonyms": _synonyms(card, claim)}
    if claim.note == ALTERNATIVE_NOTE:      # a competing explanation is searched on its own terms, not the hypothesis's
        variables.update({"claim_plain": f"a competing explanation of the hypothesis's result: {claim.subject.label} — "
                                         f"{claim.relation} — {claim.object.label}",
                          "intervention": claim.subject.label, "outcome": claim.object.label})
    version = "v2" if variables["synonyms"] else "v1"        # v2: MeSH synonyms of the card's entities (code, docs/system/card.md)
    value, _ = ask(client, role="search_queries", family=family, template="search_queries", version=version, variables=variables,
                   validate=lambda v: [] if isinstance(v.get("queries"), list) and v["queries"] else ['"queries" must be a non-empty list'],
                   rounds=2, avoid=avoid, log=log)
    raw = [q for q in (value or {}).get("queries", []) if isinstance(q, str) and q.strip()][:4]
    vocab = vocabulary(card)
    out, dropped = [], []
    for q in raw:
        f, d = filter_query(q, vocab, "light")
        dropped += d
        if f:
            out.append(f)
    if log is not None:
        log.append({"kind": "search_plan", "claim": claim.id, "model_queries": raw, "guarded": out, "dropped_terms": dropped})
    return out


def citation_expand(seed: list[str], as_of: Optional[str], retmax: int) -> list[str]:
    import httpx
    count: Counter = Counter()
    for p in seed[:TOP_SEEDS]:
        for link in ("pubmed_pubmed_refs", "pubmed_pubmed_citedin"):
            try:
                r = httpx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi",
                              params={"dbfrom": "pubmed", "db": "pubmed", "id": p, "linkname": link, "retmode": "json"}, timeout=60).json()
                ids = [str(x) for ls in r.get("linksets", []) for db in ls.get("linksetdbs", []) for x in db.get("links", [])]
            except Exception:
                ids = []
            count.update(ids)
    extra = _dated([p for p, _ in count.most_common(60) if p not in seed], as_of)
    return list(dict.fromkeys(seed[:KEEP_SEEDS] + extra + seed[KEEP_SEEDS:]))[:retmax]


GENERIC_POPULATIONS = {"", "unknown", "human", "humans", "adults", "older adults", "elderly", "aged", "older people", "people",
                       "participants", "patients", "healthy adults", "older persons", "seniors"}


def population_query(claim, card) -> Optional[str]:
    """The exact population of the trial AND the intervention's words (any of them), for outcome claims; None when the population
    is generic. Added 2026-11-07 after a blind comparison: the most informative record of a pre-sarcopenia trial (a null SPPB
    result of a resistance programme in pre-sarcopenia) was missed by the model-written queries."""
    import re
    if not (claim.link == "outcome" or (not claim.link and claim.role == "outcome")):
        return None
    pop = re.sub(r"\s+", " ", (card.pico.population.who or "").strip().lower())
    pop = re.sub(r"^(older|elderly|aged|community-dwelling)\s+(adults|people|persons|women|men)\s+(with|at risk of)\s+", "", pop)
    if pop in GENERIC_POPULATIONS or len(pop.split()) > 5:
        return None
    words = [w for lab in (i.label for i in card.pico.intervention) for w in re.findall(r"[a-z][a-z-]{3,}", lab.lower())
             if w not in {"with", "and", "the", "for", "programme", "program", "intervention", "group", "based", "daily", "weekly"}]
    if not words:
        return None
    if set(words) & EXERCISE_WORDS:
        words += ["exercise", "training"]                  # another programme of the same kind counts (class, 1/3)
    variants = {pop, pop.replace("-", " "), pop.replace("-", "")}
    d = card.identifiers.get(card.pico.population.who) if getattr(card, "identifiers", None) else None
    if d:                                                  # the condition's MeSH heading (its entry terms come with [mh])
        variants.add(d["name"].lower())
    for v in list(variants):                               # sarcopenia -> sarcopenic
        if v.endswith("ia"):
            variants.add(v[:-2] + "ic")
    pq = " OR ".join(f'"{v}"[tiab]' if " " in v or "-" in v else f"{v}[tiab]" for v in sorted(variants))
    return f"({pq}) AND (" + " OR ".join(f"{w}[tiab]" for w in dict.fromkeys(words)) + ")"


EXERCISE_WORDS = {"exercise", "exercises", "training", "squat", "squats", "resistance", "walking", "physical", "aerobic", "strength",
                  "balance", "yoga", "physiotherapy", "rehabilitation"}


def retrieve(client, family: str, avoid, claim, card, as_of: Optional[str], retmax: int, log: Optional[list] = None,
             population_first: bool = False) -> list[str]:
    """`population_first` (search mode "model_population", configs/v3-flash-n11.yaml): the exact-population query runs first
    and its hits lead the merge."""
    from hyparena.card.verifier import queries
    from hyparena.tools import pubmed
    qs = model_queries(client, family, avoid, claim, card, as_of, log)
    pq = population_query(claim, card) if population_first else None
    if pq:
        qs = [pq] + qs
        if log is not None:
            log.append({"kind": "search_population", "claim": claim.id, "query": pq})
    lists = [pubmed.search(q, retmax=retmax, as_of=as_of) for q in qs]
    merged: list[str] = []
    for i in range(retmax):
        for lst in lists:
            if i < len(lst) and lst[i] not in merged:
                merged.append(lst[i])
    merged = _dated(merged, as_of)
    pmids = citation_expand(merged, as_of, retmax) if merged else []
    for q in queries(claim, card):                           # keyword fallback
        if len(pmids) >= retmax:
            break
        pmids += [p for p in pubmed.search(q, retmax=retmax, as_of=as_of) if p not in pmids]
    return pmids[:retmax]


def _target(claim) -> str:
    """What the relevance filter is told this search is about."""
    m = claim.qualifiers.get("measure", "")
    triple = f"{claim.subject.label} — {claim.relation} — {claim.object.label}" + (f" (measure: {m})" if m and m != "unknown" else "")
    if claim.note == ALTERNATIVE_NOTE:
        return f"a competing explanation of the hypothesis's result: {triple}"
    if claim.id.startswith("an"):
        return f"the same effect in another species or for a related intervention: {triple}"
    return f"claim of the hypothesis: {triple}"


def relevance(client, avoid, claim, card, queries: list[str], ids: list[str], recs: dict, log: Optional[list] = None,
              family: str = FILTER_FAMILY) -> dict[str, int]:
    """Ratings 0-3 of the candidates by a cheap model from title and abstract (prompt search_relevance/v1, batches of 20).
    A record the model leaves unrated gets no rating (it is not read unless the rated ones are too few)."""
    from hyparena.card.llm import ask
    p = card.pico
    base = {"claim_plain": card.claim_plain, "intervention": "; ".join(i.label for i in p.intervention) or claim.subject.label,
            "population": p.population.who, "target": _target(claim), "queries": " | ".join(queries)[:1500]}
    out: dict[str, int] = {}
    for b in range(0, len(ids), FILTER_BATCH):
        batch = ids[b:b + FILTER_BATCH]
        rows = [{"n": i + 1, "title": (recs.get(x) or {}).get("title", ""), "year": (recs.get(x) or {}).get("year", ""),
                 "types": ", ".join(((recs.get(x) or {}).get("pubtypes") or [])[:3]),
                 "abstract": ((recs.get(x) or {}).get("abstract") or "")[:FILTER_ABSTRACT]} for i, x in enumerate(batch)]
        n = len(batch)
        ok = lambda v, n=n: [] if isinstance(v.get("scores"), dict) and len(v["scores"]) >= n - 1 else [f'"scores" must rate all {n} records']
        value, _ = ask(client, role="search_relevance", family=family, template="search_relevance", version="v1",
                       variables={**base, "records": rows}, validate=ok, rounds=2, avoid=avoid, log=log)
        for i, x in enumerate(batch):
            s = ((value or {}).get("scores") or {}).get(str(i + 1))
            if isinstance(s, (int, float)) and 0 <= s <= 3:
                out[x] = int(s)
    return out


def retrieve_filtered(client, family: str, avoid, claim, card, as_of: Optional[str], log: Optional[list] = None,
                      population_first: bool = True) -> list[str]:
    """Search mode "filtered" (search benchmark 2026-11-14, docs/plans/search-2026-11-14.md):
    1. the model-written queries (and the exact-population query for an outcome claim), each up to 200 papers before T;
    2. the candidates ordered by BM25 of the query terms against title and abstract;
    3. the references and citing papers of the first 5 join (dated before T), and BM25 orders all again;
    4. a cheap model rates the first 100 from title and abstract (0-3);
    5. read: every paper rated 3, filled up to 10 with papers rated 2, at most 20.
    With no candidates the keyword queries of the verifier are used as before."""
    from hyparena.card import search_rank as rank
    from hyparena.card.verifier import queries as keyword_queries
    from hyparena.tools import pubmed
    qs = model_queries(client, family, avoid, claim, card, as_of, log)
    pq = population_query(claim, card) if population_first else None
    if pq:
        qs = [pq] + qs
    cand: list[str] = []
    for q in qs:
        cand += [p for p in pubmed.search(q, retmax=PER_QUERY, as_of=as_of) if p not in cand]
    cand = _dated(cand, as_of)
    if not cand:
        out: list[str] = []
        for q in keyword_queries(claim, card):
            out += [p for p in pubmed.search(q, retmax=CAP, as_of=as_of) if p not in out]
            if len(out) >= CAP:
                break
        if log is not None:
            log.append({"kind": "search_filter", "claim": claim.id, "candidates": 0, "fallback": "keywords", "selected": out[:CAP]})
        return out[:CAP]
    terms = rank.query_terms(qs)
    recs = pubmed.fetch(cand)
    doc = lambda p: rank.tokens(f"{(recs.get(p) or {}).get('title', '')} {(recs.get(p) or {}).get('abstract', '')}")
    order = rank.bm25(terms, {p: doc(p) for p in cand})
    linked: Counter = Counter()
    for s in order[:TOP_SEEDS]:
        for name in ("pubmed_pubmed_refs", "pubmed_pubmed_citedin"):
            linked.update(_links(s, name))
    new = _dated([p for p, _ in linked.most_common() if p not in cand][:LINKED_MAX], as_of)
    if new:
        recs.update(pubmed.fetch(new))
        order = rank.bm25(terms, {p: doc(p) for p in cand + new})
    top = order[:RATED]
    scores = relevance(client, avoid, claim, card, qs, top, recs, log=log)
    chosen = rank.select(top, scores, fill=FILL, cap=CAP)
    if log is not None:
        log.append({"kind": "search_filter", "claim": claim.id, "candidates": len(cand), "linked": len(new),
                    "rated": len(scores), "ratings": dict(Counter(scores.values())), "selected": chosen})
    return chosen


def _links(pmid: str, name: str) -> list[str]:
    import httpx
    try:
        r = httpx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi",
                      params={"dbfrom": "pubmed", "db": "pubmed", "id": pmid, "linkname": name, "retmode": "json"}, timeout=60).json()
        return [str(x) for ls in r.get("linksets", []) for db in ls.get("linksetdbs", []) for x in db.get("links", [])]
    except Exception:                                     # noqa: BLE001 - a failed link is no candidates, not an error
        return []
