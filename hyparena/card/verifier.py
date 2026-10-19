"""Verifier: claim → evidence records (card spec section 7). Sources: DrugAge (curated, deterministic, lifespan
claims) and PubMed abstracts (an LLM extracts records). Code then checks that every quote is a verbatim
substring of its abstract, drops those that are not, and leaves statuses to the rules."""
from __future__ import annotations

import re
from typing import Optional

from hyparena.card.llm import ask
from hyparena.card.models import Claim, ClaimVerification, EvidenceRecord, HypothesisCard, ProgramInfo, Refusal, Verification
from hyparena.card.rules import claim_endpoint
from hyparena.card.sources import drugage_records
from hyparena.tools import pubmed

TEMPLATE = ("verify_claim", "v1")
REL_WORDS = {"extends_lifespan_in": "lifespan", "shortens_lifespan_in": "lifespan", "no_lifespan_effect_in": "lifespan",
             "improves_healthspan_in": "healthspan OR physical function", "changes_biomarker": "", "predicts": "predicts",
             "inhibits": "inhibits", "activates": "activates", "increases_expression": "expression",
             "decreases_expression": "expression", "promotes": "", "suppresses": "", "part_of": "",
             "associated_with": "", "affects_hallmark": "", "translates_to": "", "other": ""}


def _clean(s: str) -> str:
    return re.sub(r"[\"'()\[\]/]", " ", s or "").strip()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("‐", "-").replace("–", "-")).strip().lower()


SPECIES_WORDS = {"older adults": "humans", "healthy older adults": "humans", "adults": "humans", "human": "humans",
                 "mouse": "mice", "mice": "mice", "rat": "rats", "nematode": "C. elegans", "worm": "C. elegans",
                 "fly": "Drosophila", "yeast": "yeast"}


def _core(label: str, card: HypothesisCard) -> str:
    """The entity name for a search: the card's intervention label when the claim subject contains it
    (drops regimen words such as "weekly low-dose")."""
    low = label.lower()
    hits = [i.label for i in card.pico.intervention if i.label.lower() in low]
    return " ".join(hits) if hits else label


def queries(claim: Claim, card: HypothesisCard) -> list[str]:
    """Search terms: entity, relation word, object; the organism as a search word."""
    subject = _core(claim.subject.label, card)
    obj = claim.object.label
    organism = SPECIES_WORDS.get(obj.strip().lower()) or SPECIES_WORDS.get(claim.qualifiers.get("species", "").strip().lower(), "")
    obj_term = "" if obj.strip().lower() in SPECIES_WORDS else obj
    words = [subject, REL_WORDS.get(claim.relation, ""), obj_term, organism]
    q1 = " ".join(_clean(w) for w in words if w and w != "unknown")
    q2 = " ".join(_clean(w) for w in (subject, obj_term or organism) if w and w != "unknown")
    return list(dict.fromkeys([q for q in (q1, q2) if q]))


def _validate(value: dict, abstracts: dict[str, dict]) -> list[str]:
    problems = []
    for i, r in enumerate(value.get("records") or []):
        if not isinstance(r, dict):
            problems.append(f"record {i}: not an object")
            continue
        pmid = str(r.get("pmid", "")).replace("PMID:", "").strip()
        a = abstracts.get(pmid)
        if a is None:
            problems.append(f"record {i}: PMID {pmid} is not one of the given abstracts")
        elif _norm(r.get("quote", "")) not in _norm(a["title"] + " " + a["abstract"]):
            problems.append(f"record {i} (PMID {pmid}): the quote is not copied verbatim from the abstract")
    return problems


def verify_claim(client, family: str, avoid: frozenset, claim: Claim, card: HypothesisCard,
                 as_of: Optional[str] = None, retmax: int = 6, log: Optional[list] = None) -> ClaimVerification:
    cv = ClaimVerification(id=claim.id)
    allowed = None
    support, against = drugage_records(claim)
    if as_of and (support or against):
        from hyparena.backtest import _pubdates
        dates = _pubdates([r.linked_pmid for r in support + against])
        allowed = {p for p, d in dates.items() if d <= as_of}
        support = [r for r in support if r.linked_pmid in allowed]
        against = [r for r in against if r.linked_pmid in allowed]
    cv.evidence += support
    cv.counterevidence += against
    pmids = []
    for q in queries(claim, card):
        if q:
            pmids += [p for p in pubmed.search(q, retmax=retmax, as_of=as_of) if p not in pmids]
        if len(pmids) >= retmax:
            break
    pmids = pmids[:retmax]
    abstracts = {p: a for p, a in pubmed.fetch(pmids).items() if a.get("abstract")}
    if log is not None:
        log.append({"kind": "search", "claim": claim.id, "queries": queries(claim, card), "as_of": as_of,
                    "pmids": list(abstracts), "drugage": [r.record_id for r in support + against]})
    if not abstracts:
        cv.notes = "no abstracts found"
        return cv
    p = card.pico
    variables = {"claim": claim, "qualifiers": ", ".join(f"{k}: {v}" for k, v in claim.qualifiers.items() if v and v != "unknown"),
                 "endpoint": claim_endpoint(claim), "claim_plain": card.claim_plain,
                 "population": ", ".join(f"{k} {v}" for k, v in p.population.model_dump().items() if v and v != "unknown") or "unknown",
                 "intervention": "; ".join(f"{i.label} ({i.regimen})" for i in p.intervention) or "unknown",
                 "comparator": p.comparator.label,
                 "abstracts": [{"pmid": k, "year": a["year"], "title": a["title"], "abstract": a["abstract"],
                                "review": pubmed.is_review(a)} for k, a in abstracts.items()]}
    value, fam = ask(client, role="verify_claim", family=family, template=TEMPLATE[0], version=TEMPLATE[1],
                     variables=variables, validate=lambda v: _validate(v, abstracts), rounds=2, avoid=avoid, log=log)
    rejected = []
    for r in (value or {}).get("records") or []:
        if not isinstance(r, dict):
            continue
        pmid = str(r.get("pmid", "")).replace("PMID:", "").strip()
        a = abstracts.get(pmid)
        quote = r.get("quote", "")
        if a is None or _norm(quote) not in _norm(a["title"] + " " + a["abstract"]):
            rejected.append(pmid)
            continue                                      # never keep a quote that is not in the source
        review = pubmed.is_review(a)
        qm = {k: str(v) for k, v in (r.get("qualifiers_match") or {}).items() if str(v) in ("yes", "no", "n/a")}
        qm["intervention_match"] = r.get("intervention_match") or "exact"
        prog = r.get("program") or ""
        rec = EvidenceRecord(
            source="PubMed", record_id=f"PMID:{pmid}", epistemic_type="A_text",
            study_type="review" if review else (r.get("study_type") or "other"),
            lab_or_cohort=f"PMID:{pmid}", derived_from="review" if review else "",
            species=r.get("species") or "unknown", system=r.get("system") if r.get("system") in ("ex_vivo", "in_vitro") else "",
            quote=quote, quote_role=r.get("quote_role") if r.get("quote_role") in ("finding", "background", "speculation") else "background",
            endpoint=r.get("endpoint") if r.get("endpoint") in ("lifespan", "healthspan", "biomarker", "disease", "mechanism") else "unknown",
            effect_percent=r.get("effect_percent") if isinstance(r.get("effect_percent"), (int, float)) else None,
            sexes=[s for s in (r.get("sexes") or []) if s in ("male", "female")], qualifiers_match=qm,
            program=ProgramInfo(name=prog) if prog in ("ITP", "CITP") else None,
            flags=[f for f in (r.get("flags") or []) if isinstance(f, str)], retrieved_at=a.get("year", ""),
            notes=f"extracted by {fam}")
        stance = r.get("stance")
        need = claim_endpoint(claim)
        if stance == "supports":
            cv.evidence.append(rec)
        elif stance == "refutes":
            cv.counterevidence.append(rec)
        elif need and rec.endpoint not in ("unknown", need) and rec.quote_role == "finding":
            cv.refusals.append(Refusal(type="endpoint_mismatch", record_id=rec.record_id, quote=quote,
                                       notes=f"measures {rec.endpoint}, the claim is about {need}"))
    if rejected:
        cv.notes = (cv.notes + "; " if cv.notes else "") + f"quotes not found verbatim, dropped: {', '.join(rejected)}"
    return cv


def verify(client, families: list[str], writer: str, card: HypothesisCard, as_of: Optional[str] = None,
           log: Optional[list] = None, map_fn=map) -> Verification:
    """All declared claims; the verifier's family is never the writer's (its records feed the ranking)."""
    allowed = [f for f in families if f != writer] or families
    tasks = [(c, allowed[i % len(allowed)]) for i, c in enumerate(card.claims)]
    cvs = list(map_fn(lambda t: verify_claim(client, t[1], frozenset({writer}), t[0], card, as_of, log=log), tasks))
    return Verification(card_id=card.id, claims=cvs)
