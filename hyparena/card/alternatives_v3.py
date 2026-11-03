"""Method v3: alternatives proposed by a model (docs/spec/method-v3.md, section 4).

One call per hypothesis (prompt propose_alternatives/v1) over the abstracts already read for it, dated by T. Code keeps only
support PMIDs from that list (an alternative without them weighs nothing in the rules), drops an alternative eliminated by
both outcomes, and keeps at most 5. The support of each alternative is checked by the verifier like a claim (rules, step 3).
"""
from __future__ import annotations

import typing
from typing import Optional

from hyparena.card.llm import ask
from hyparena.card.models import HypothesisCard, ProposedAlternative, Relation

MAX_ALTERNATIVES = 5
MAX_ABSTRACTS = 25


def _experiment(card: HypothesisCard) -> str:
    e = card.decisive_experiment
    parts = [f"system {e.system}", f"design {e.design}", f"control {e.control}",
             f"n {e.n_planned}" if e.n_planned else "", f"primary outcome {e.primary_outcome}", f"endpoint {e.endpoint}",
             f"duration {e.duration_class}"]
    return ", ".join(p for p in parts if p and not p.endswith("unknown") and not p.endswith("None"))


def propose(client, family: str, card: HypothesisCard, abstracts: dict[str, dict], as_of: Optional[str],
            avoid=frozenset(), log: Optional[list] = None) -> list[ProposedAlternative]:
    """`abstracts`: PMID -> {title, abstract, year} of the papers read for this hypothesis (already dated by T)."""
    allowed = {str(p) for p in abstracts}
    items = [{"pmid": p, "year": a.get("year", ""), "title": a.get("title", ""), "abstract": a.get("abstract", "")[:1500]}
             for p, a in list(abstracts.items())[:MAX_ABSTRACTS]]
    chain = [c for c in card.claims if c.link or c.role in ("outcome", "mechanism", "premise")]
    variables = {"as_of": as_of or "today", "claim_plain": card.claim_plain, "chain": chain, "experiment": _experiment(card) or "not stated",
                 "abstracts": items, "relations": ", ".join(typing.get_args(Relation))}

    def validate(v):
        alts = v.get("alternatives")
        return [] if isinstance(alts, list) else ['the reply must be an object with an "alternatives" list']
    value, _ = ask(client, role="propose_alternatives", family=family, template="propose_alternatives", version="v1",
                   variables=variables, validate=validate, rounds=2, avoid=avoid, log=log)
    out: list[ProposedAlternative] = []
    for i, raw in enumerate((value or {}).get("alternatives") or [], start=1):
        if not isinstance(raw, dict) or len(out) >= MAX_ALTERNATIVES:
            continue
        raw = {**raw, "id": f"p{i}", "support_pmids": [str(p).replace("PMID:", "").strip() for p in raw.get("support_pmids") or []
                                                     if str(p).replace("PMID:", "").strip() in allowed]}
        if raw.get("relation") not in typing.get_args(Relation):
            raw["relation"] = "other"
        try:
            out.append(ProposedAlternative.model_validate(raw))
        except Exception:                                   # eliminated by both outcomes, or malformed: dropped
            continue
    return out
