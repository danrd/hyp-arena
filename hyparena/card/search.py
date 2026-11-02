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


def _dated(pmids: list[str], as_of: Optional[str]) -> list[str]:
    if not as_of or not pmids:
        return list(pmids)
    from hyparena import backtest
    d = backtest._pubdates(pmids)
    return [p for p in pmids if p in d and d[p] <= as_of]


def model_queries(client, family: str, avoid, claim, card, as_of: Optional[str], log: Optional[list] = None) -> list[str]:
    from hyparena.card.llm import ask
    from hyparena.card.search_vocab import filter_query, vocabulary
    p = card.pico
    variables = {"as_of": as_of or "today", "claim_plain": card.claim_plain, "claim": claim,
                 "qualifiers": ", ".join(f"{k}: {v}" for k, v in claim.qualifiers.items() if v and v != "unknown"),
                 "intervention": "; ".join(i.label for i in p.intervention) or claim.subject.label,
                 "population": p.population.label, "outcome": p.outcome.metric or claim.object.label}
    value, _ = ask(client, role="search_queries", family=family, template="search_queries", version="v1", variables=variables,
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


def retrieve(client, family: str, avoid, claim, card, as_of: Optional[str], retmax: int, log: Optional[list] = None) -> list[str]:
    from hyparena.card.verifier import queries
    from hyparena.tools import pubmed
    qs = model_queries(client, family, avoid, claim, card, as_of, log)
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
