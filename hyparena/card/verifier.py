"""Verifier: claim → evidence records (card spec section 7). Sources: DrugAge (curated, deterministic, lifespan
claims) and PubMed abstracts (an LLM extracts records). Code then checks that every quote is a verbatim
substring of its abstract, drops those that are not, and leaves statuses to the rules."""
from __future__ import annotations

import re
from typing import Optional

from hyparena.card.llm import ask, parse_objects
from hyparena.card.models import (UNKNOWN, Claim, ClaimVerification, Entity, EvidenceRecord,
                                  HypothesisCard, ProgramInfo, Refusal, Verification)
from hyparena.card.rules import ORGANISM_PATTERNS, claim_organism, claim_endpoint, pico_value, quote_organisms, species_key
from hyparena.card import contexts
from hyparena.card.entities import subject_compounds
from hyparena.card.sources import drugage_records, lifespan_wanted
from hyparena.tools import pubmed

TEMPLATE = ("verify_claim", "v4")
REL_WORDS = {"extends_lifespan_in": "lifespan", "shortens_lifespan_in": "lifespan", "no_lifespan_effect_in": "lifespan",
             "slows_aging_in": "slows aging",
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


def queries(claim, card: HypothesisCard) -> list[str]:
    """Search terms: entity, relation word, object; the organism as a search word. When the object is not an
    organism, also the relation alone ("rapamycin slows aging mice"): long object phrases often match nothing."""
    subject = _core(claim.subject.label, card)
    obj = claim.object.label
    organism = SPECIES_WORDS.get(obj.strip().lower()) or SPECIES_WORDS.get(claim.qualifiers.get("species", "").strip().lower(), "")
    obj_term = "" if obj.strip().lower() in SPECIES_WORDS else obj
    rel = REL_WORDS.get(claim.relation, "")

    def q(*words):
        return " ".join(_clean(w) for w in words if w and w != UNKNOWN)

    q1 = q(subject, rel, obj_term, organism)
    q_rel = q(subject, rel, organism) if rel and obj_term and organism else ""
    q2 = q(subject, obj_term or organism)
    q3 = q(subject, obj_term, organism, "lifespan" if "lifespan" not in q1 else "")
    return list(dict.fromkeys([x for x in (q1, q_rel, q2, q3) if x]))


def _context_match(qm: dict[str, str], claim, card: HypothesisCard, quote: str = "") -> dict[str, str]:
    """Spec 7: a qualifier the card leaves unknown gives n/a, never a mismatch."""
    out = dict(qm)
    for key in ("sex", "age_at_start", "dose", "comparator", "strain"):
        value = claim.qualifiers.get(key) or (pico_value(card, key) if key != "dose"
                                              else next((i.regimen for i in card.pico.intervention), UNKNOWN))
        if out.get(key) == "no" and (not value or value.strip().lower() in (UNKNOWN, "", "n/a")):
            out[key] = "n/a"
    if out.get("species") == "no" and not claim_organism(claim):
        out["species"] = "n/a"                             # the claim names no organism: unknown, not a mismatch
    # the quote names organisms and the claim's is not among them (e.g. a sentence about yeast, worms and flies
    # extracted as a mouse finding): a species mismatch, whatever the extractor said
    organism = species_key(claim.qualifiers.get("species", "")) or species_key(claim.object.label)
    named = quote_organisms(quote)
    if organism in ORGANISM_PATTERNS and named and organism not in named:
        out["species"] = "no"
    return out


def parse_records(text: str) -> Optional[dict]:
    """{"records": [...]}; from a reply cut off at the token limit, the records that are complete."""
    found = parse_objects(text)
    whole = next((v for v in found if isinstance(v.get("records"), list)), None)
    if whole is not None:
        return whole
    records = [v for v in found if "pmid" in v and "quote" in v]
    return {"records": records, "truncated": True} if records else None


def _validate(value: dict, abstracts: dict[str, dict]) -> list[str]:
    if not isinstance(value.get("records"), list):
        return ['the reply must be an object with a "records" list']
    problems = ["the reply was cut off before the end: reply again, complete"] if value.get("truncated") else []
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


def curated(claim, card: HypothesisCard, as_of: Optional[str] = None) -> tuple[list[EvidenceRecord], list[EvidenceRecord]]:
    """DrugAge records for a lifespan claim (deterministic), restricted to papers published by `as_of`."""
    comps = subject_compounds(claim.subject.label, card)
    support, against = drugage_records(claim, cid=comps[0].cid if comps and len(comps) == 1 else None)
    if as_of and (support or against):
        from hyparena.backtest import _pubdates
        dates = _pubdates([r.linked_pmid for r in support + against])
        allowed = {p for p, d in dates.items() if d <= as_of}
        support = [r for r in support if r.linked_pmid in allowed]
        against = [r for r in against if r.linked_pmid in allowed]
    return support, against


def verify_claim(client, family: str, avoid: frozenset, claim, card: HypothesisCard,
                 as_of: Optional[str] = None, retmax: int = 8, log: Optional[list] = None,
                 fallback: Optional[str] = None, expert_pmids: Optional[list[tuple[str, str]]] = None) -> ClaimVerification:
    """`fallback`: the family asked when `family`'s reply is cut off with no complete record (gemini stops in
    the middle of verbatim quotes, most likely its recitation filter)."""
    cv = ClaimVerification(id=claim.id)
    support, against = curated(claim, card, as_of)
    cv.evidence += support
    cv.counterevidence += against
    pmids = []
    for q in queries(claim, card):
        if q:
            pmids += [p for p in pubmed.search(q, retmax=retmax, as_of=as_of) if p not in pmids]
        if len(pmids) >= retmax:
            break
    pmids = pmids[:retmax]
    by_expert = {pmid: did for pmid, did in (expert_pmids or [])}    # sources an expert gave (spec 7a)
    pmids = list(by_expert) + [p for p in pmids if p not in by_expert]
    abstracts = {p: a for p, a in pubmed.fetch(pmids).items() if a.get("abstract")}
    if log is not None:
        log.append({"kind": "search", "claim": claim.id, "queries": queries(claim, card), "as_of": as_of,
                    "expert_pmids": list(by_expert),
                    "pmids": list(abstracts), "drugage": [r.record_id for r in support + against]})
    if not abstracts:
        cv.notes = "no abstracts found"
        return cv
    p = card.pico
    negated = claim.qualifiers.get("direction", "").lower() in ("no_effect", "none", "no", "not", "no effect")
    contrast = next((a for a in card.declared_alternatives if a.id == claim.qualifiers.get("contrast")), None)
    variables = {"claim": claim, "negated": negated, "alternative": claim.role == "alternative",
                 "contrast": contrast.subject.label + " " + contrast.relation + " " + contrast.object.label if contrast else "",
                 "qualifiers": ", ".join(f"{k}: {v}" for k, v in claim.qualifiers.items()
                                         if v and v != "unknown" and k != "contrast"),
                 "endpoint": claim_endpoint(claim), "claim_plain": card.claim_plain,
                 "population": ", ".join(f"{k} {v}" for k, v in p.population.model_dump().items() if v and v != "unknown") or "unknown",
                 "intervention": "; ".join(f"{i.label} ({i.regimen})" for i in p.intervention) or "unknown",
                 "comparator": p.comparator.label,
                 "abstracts": [{"pmid": k, "year": a["year"], "title": a["title"], "abstract": a["abstract"],
                                "review": pubmed.is_review(a)} for k, a in abstracts.items()]}
    value, fam = ask(client, role="verify_claim", family=family, template=TEMPLATE[0], version=TEMPLATE[1],
                     variables=variables, validate=lambda v: _validate(v, abstracts), rounds=2, avoid=avoid, log=log,
                     parse=parse_records)
    if fallback and fallback != fam and (value is None or (value.get("truncated") and not value.get("records"))):
        value, fam = ask(client, role="verify_claim", family=fallback, template=TEMPLATE[0], version=TEMPLATE[1],
                         variables=variables, validate=lambda v: _validate(v, abstracts), rounds=2, avoid=avoid,
                         log=log, parse=parse_records)
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
        qm = _context_match(qm, claim, card, quote)
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
            notes=f"extracted by {fam}" + (f"; source given by expert decision {by_expert[pmid]}" if pmid in by_expert else ""))
        contexts.flag(rec, a["title"] + " " + a["abstract"])
        stance = r.get("stance")
        need = claim_endpoint(claim)
        effect = r.get("effect") if r.get("effect") in ("increase", "decrease", "no_effect") else "unknown"
        rec.effect = effect
        if need == "lifespan" and rec.endpoint == "lifespan" and rec.quote_role == "finding" and effect != "unknown":
            # the stance of a lifespan finding follows from its direction, as for DrugAge (code, not the extractor)
            coded = "supports" if effect == lifespan_wanted(claim) else "refutes"
            if coded != stance:
                rec.notes += f"; stance set from the effect direction ({effect}); the extractor said {stance}"
            stance = coded
        mismatched = [k for k, v in qm.items() if v == "no" and k != "intervention_match"]
        if stance in ("supports", "refutes") and mismatched and set(mismatched) <= set(claim.inherited_from_pico):
            # a mismatch only on a value inherited from PICO: a soft refusal, not a status (spec 7)
            cv.refusals.append(Refusal(type="inherited_mismatch", record_id=rec.record_id, quote=quote,
                                       notes=f"{', '.join(mismatched)} inherited from PICO; the record is about {rec.species}"))
        elif stance == "supports":
            cv.evidence.append(rec)
        elif stance == "refutes":
            cv.counterevidence.append(rec)
        elif need and rec.endpoint not in ("unknown", need) and rec.quote_role == "finding":
            cv.refusals.append(Refusal(type="endpoint_mismatch", record_id=rec.record_id, quote=quote,
                                       notes=f"measures {rec.endpoint}, the claim is about {need}"))
    if rejected:
        cv.notes = (cv.notes + "; " if cv.notes else "") + f"quotes not found verbatim, dropped: {', '.join(rejected)}"
    if (value or {}).get("truncated"):
        cv.notes = (cv.notes + "; " if cv.notes else "") + "reply cut off: only its complete records were kept"
    return cv


def analog_probes(card: HypothesisCard) -> list[Claim]:
    """Claims the verifier adds in its own layer (spec 4, 8): when an interventional hypothesis is about
    humans, the same intervention's lifespan and healthspan effect in mice, which can set the effect level
    below the human rungs."""
    out = card.outcome_claim
    if card.hypothesis_type != "interventional" or not card.pico.intervention or out is None:
        return []
    human = any(w in (out.object.label + " " + card.pico.population.label + " " + (card.pico.population.taxon or "")).lower()
                for w in ("human", "adult", "people", "patient", "9606"))
    if not human:
        return []
    label = " + ".join(i.label for i in card.pico.intervention)
    return [Claim(id="an1", subject=Entity(label=label), relation="extends_lifespan_in", object=Entity(label="mouse"),
                  qualifiers={"species": "mouse"}, role="analog", note="added by the verifier"),
            Claim(id="an2", subject=Entity(label=label), relation="improves_healthspan_in", object=Entity(label="mouse"),
                  qualifiers={"species": "mouse"}, role="analog", note="added by the verifier")]


def verify(client, families: list[str], writer: str, card: HypothesisCard, as_of: Optional[str] = None,
           log: Optional[list] = None, map_fn=map,
           expert_sources: Optional[dict[str, list[tuple[str, str]]]] = None) -> Verification:
    """All declared claims, the rejected alternatives of a contrast (checked like claims, spec 7), plus analog
    probes; the verifier's family is never the writer's (its records feed the ranking)."""
    allowed = [f for f in families if f != writer] or families
    probes = analog_probes(card)
    claims = card.claims + card.rejected_alternatives + probes
    tasks = [(c, allowed[i % len(allowed)], allowed[(i + 1) % len(allowed)]) for i, c in enumerate(claims)]
    expert_sources = expert_sources or {}
    cvs = list(map_fn(lambda t: verify_claim(client, t[1], frozenset({writer}), t[0], card, as_of, log=log,
                                             fallback=t[2], expert_pmids=expert_sources.get(t[0].id)), tasks))
    added = {c.id for c in probes}
    for cv, c in zip(cvs, claims):
        if cv.id in added:
            cv.added_claim = c
    return Verification(card_id=card.id, claims=cvs)
