"""Alternative explanations in the verified layer (card spec 8c). Added by code after the verifier:

- declared rejected alternatives (`a<N>`, the Y of a contrast) carry their claim status from the rules;
- the checklist of failure modes (`alt<N>`, 14 rows): each row has an inclusion rule over card fields and
  evidence-record fields, no LLM, so two cards with the same fields get the same alternatives.

Checking (spec 8c, cost): one verifier call per hypothesis over the abstracts already retrieved. For every
included row the model says whether an abstract reports the discriminating control for this intervention;
code keeps a finding only with a verbatim quote from a given abstract. Found with the effect persisting →
`excluded_by_evidence`; found with the effect gone → `supported` (the alternative explains it); not found →
`open`. A dedicated search per alternative (`deep_check`) only for strong hypotheses (P(top-k) >= 0.5). The
prediction table and informativeness come at stage C with debates; until then informativeness is unknown."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from hyparena.card.llm import ask
from hyparena.card.models import Alternative, EvidenceRecord, HypothesisCard, Verification
from hyparena.card.rules import (HETEROGENEOUS, _all_claims, admissible, same_intervention, species_key, statuses,
                                 strain_key)
from hyparena.tools import pubmed

TEMPLATE = ("check_alternatives", "v1")
ANIMALS = {"mouse", "rat", "worm", "fly", "killifish", "dog", "primate"}


@dataclass(frozen=True)
class Row:
    id: str
    explanation: str
    design: str
    terms: tuple[str, ...]                      # search words for the dedicated search (deep_check)
    include: Callable[["Fields"], bool]


@dataclass
class Fields:
    """The card and record fields the inclusion rules read."""
    type: str
    species: str                                # species_key of the population: mouse, worm, human ...
    endpoint: str
    intervention_types: set[str]
    routes: set[str]
    support: list[EvidenceRecord]               # admissible support of the outcome and same-intervention analogs
    engagement: list[EvidenceRecord]            # admissible support of inhibits/activates claims
    has_target_claim: bool


def fields(card: HypothesisCard, ver: Verification) -> Fields:
    pairs = _all_claims(card, ver)
    support = [r for c, cv in pairs
               if c.role == "outcome" or (c.role in ("analog", "translation") and same_intervention(c, card))
               for r in cv.evidence if admissible(r, c)]
    target = [(c, cv) for c, cv in pairs if c.relation in ("inhibits", "activates")]
    pop = card.pico.population
    return Fields(type=card.hypothesis_type, species=species_key(pop.label) or species_key(pop.taxon or ""),
                  endpoint=card.pico.outcome.endpoint, intervention_types={i.type for i in card.pico.intervention},
                  routes={i.route for i in card.pico.intervention},
                  support=support, engagement=[r for c, cv in target for r in cv.evidence if admissible(r, c)],
                  has_target_claim=bool(target))


def _given(v: str) -> str:
    v = (v or "").strip().lower()
    return "" if v in ("unknown", "n/a", "none") else v


def _one_inbred_strain(f: Fields) -> bool:
    strains = {strain_key(_given(r.strain)) for r in f.support}
    if not f.support or "" in strains or len(strains) != 1:
        return False
    return not any(strain_key(h) in next(iter(strains)) for h in HETEROGENEOUS)


def _one_sex(f: Fields) -> bool:
    sexes = {r.sex for r in f.support}
    return bool(f.support) and "both" not in sexes and not {"male", "female"} <= sexes


def _one_dose_and_age(f: Fields) -> bool:
    doses = {_given(r.dose) for r in f.support} - {""}
    ages = {_given(r.age_at_start) for r in f.support} - {""}
    return bool(f.support) and len(doses) <= 1 and len(ages) <= 1


def _lifespan_animal_not_diet(f: Fields) -> bool:
    return f.endpoint == "lifespan" and f.species in ANIMALS and "diet" not in f.intervention_types


CHECKLIST: list[Row] = [
    Row("food_intake", "effect via reduced food intake (hidden caloric restriction)",
        "pair feeding; food intake and body weight measured", ("food intake", "pair-fed", "body weight"),
        _lifespan_animal_not_diet),
    Row("body_temperature", "effect via lower body temperature", "core temperature monitoring; thermoneutral housing",
        ("body temperature", "thermoneutral"), _lifespan_animal_not_diet),
    Row("microbes", "effect via bacteria or microbiota",
        "worms: killed bacteria, other strains; mice: antibiotics or germ-free animals",
        ("bacteria", "microbiota", "germ-free", "antibiotics"),
        lambda f: f.species == "worm" or (f.species == "mouse" and bool(f.routes & {"diet", "water", "oral"}))),
    Row("exposure_failed", "the compound did not reach the intended exposure",
        "measured concentration in food or blood", ("blood levels", "plasma concentration", "pharmacokinetics"),
        lambda f: bool(f.routes & {"diet", "water"})),
    Row("genetic_background", "effect of the genetic background, not of the intervention",
        "backcrossed lines, proper transgenic controls, genetically heterogeneous mice, strain panel (CITP)",
        ("genetic background", "backcrossed", "outcrossed", "strains"),
        lambda f: "gene" in f.intervention_types or _one_inbred_strain(f)),
    Row("disease_specific", "effect through one disease (e.g. cancer), not through aging",
        "cause of death and pathology; censoring disease deaths", ("cause of death", "pathology", "cancer"),
        lambda f: f.species == "mouse" and f.endpoint == "lifespan"),
    Row("sex_specific", "effect in one sex only", "both sexes", ("sex differences", "male", "female"), _one_sex),
    Row("dose_regimen", "effect only at this dose or start age", "several doses and start ages",
        ("dose-response", "doses", "late-life"), _one_dose_and_age),
    Row("off_target", "effect not through the named target",
        "knockout or knockdown of the target: effect persists → wrong mechanism", ("knockout", "knockdown"),
        lambda f: f.type == "mechanistic" and f.has_target_claim),
    Row("assay_artifact", "target engagement is an assay artifact", "an independent assay",
        ("artifact", "independent assay"),
        lambda f: f.type == "mechanistic" and f.has_target_claim and bool(f.engagement)
        and all(r.system == "in_vitro" for r in f.engagement)),
    Row("confounding", "confounders explain the association", "discordant twins, Mendelian randomization, RCT",
        ("Mendelian randomization", "twins", "confounding"), lambda f: f.type == "observational"),
    Row("reverse_causation", "the outcome causes the exposure", "temporal order, Mendelian randomization",
        ("Mendelian randomization", "reverse causation"), lambda f: f.type == "observational"),
    Row("age_proxy", "the marker only reflects chronological age", "prediction beyond chronological age",
        ("chronological age", "independent of age"), lambda f: f.type == "biomarker"),
    Row("disease_proxy", "the marker reflects disease, not aging", "exclude people with the disease; independent cohort",
        ("healthy", "independent cohort"), lambda f: f.type == "biomarker"),
]
BY_ID = {r.id: r for r in CHECKLIST}


def rows(card: HypothesisCard, ver: Verification) -> list[Alternative]:
    """The alternatives row of a verified card: declared rejected alternatives with their claim status, then
    the checklist rows whose inclusion rule holds (open until checked; results of an earlier check are kept),
    then alternatives from other sources unchanged."""
    st = statuses(card, ver)
    out = [Alternative(id=a.id, type="declared", source="declared", status=st.get(a.id, "unverified"),
                       explanation=f"{a.subject.label} {a.relation} {a.object.label}")
           for a in card.rejected_alternatives]
    f = fields(card, ver)
    checked = {a.type: a for a in ver.alternatives if a.source == "checklist" and a.status != "open"}
    for n, r in enumerate((r for r in CHECKLIST if r.include(f)), 1):
        alt = Alternative(id=f"alt{n}", type=r.id, source="checklist", explanation=r.explanation,
                          discriminating_design=r.design)
        if r.id in checked:                                # a result of an earlier check stays
            old = checked[r.id]
            alt.status, alt.record_id, alt.quote = old.status, old.record_id, old.quote
        out.append(alt)
    out += [a for a in ver.alternatives if a.source not in ("checklist", "declared")]   # proximity, debate, expert
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("‐", "-").replace("–", "-")).strip().lower()


def _validate(value: dict, ids: set[str], abstracts: dict[str, dict]) -> list[str]:
    items = value.get("alternatives")
    if not isinstance(items, list):
        return ['the reply must be an object with an "alternatives" list']
    problems = []
    for i, x in enumerate(items):
        if not isinstance(x, dict) or x.get("id") not in ids:
            problems.append(f"item {i}: id must be one of {sorted(ids)}")
            continue
        if x.get("found") in ("excluded", "supported"):
            pmid = str(x.get("pmid", "")).replace("PMID:", "").strip()
            a = abstracts.get(pmid)
            if a is None:
                problems.append(f"{x['id']}: PMID {pmid} is not one of the given abstracts")
            elif _norm(x.get("quote", "")) not in _norm(a["title"] + " " + a["abstract"]):
                problems.append(f"{x['id']}: the quote is not copied verbatim from PMID {pmid}")
    return problems


def check(client, family: str, card: HypothesisCard, ver: Verification, pmids: Optional[list[str]] = None,
          avoid: frozenset = frozenset(), log: Optional[list] = None, only: Optional[set[str]] = None) -> Verification:
    """One call: for the open checklist rows (or `only` these ids), is the discriminating control reported in
    the abstracts (default: the ones the verifier already read, `ver.searched_pmids`)?"""
    todo = [a for a in ver.alternatives if a.source == "checklist" and a.status == "open" and (only is None or a.id in only)]
    abstracts = {p: a for p, a in pubmed.fetch(list(pmids if pmids is not None else ver.searched_pmids)).items()
                 if a.get("abstract")}
    if not todo or not abstracts:
        return ver
    variables = {"claim_plain": card.claim_plain,
                 "intervention": "; ".join(i.label for i in card.pico.intervention) or "unknown",
                 "population": card.pico.population.label, "endpoint": card.pico.outcome.endpoint,
                 "alternatives": [{"id": a.id, "explanation": a.explanation, "design": a.discriminating_design} for a in todo],
                 "abstracts": [{"pmid": k, "year": a["year"], "title": a["title"], "abstract": a["abstract"]}
                               for k, a in abstracts.items()]}
    ids = {a.id for a in todo}
    value, fam = ask(client, role="check_alternatives", family=family, template=TEMPLATE[0], version=TEMPLATE[1],
                     variables=variables, validate=lambda v: _validate(v, ids, abstracts), rounds=2, avoid=avoid, log=log)
    by_id = {a.id: a for a in todo}
    for x in (value or {}).get("alternatives") or []:
        if not isinstance(x, dict) or x.get("id") not in by_id or x.get("found") not in ("excluded", "supported"):
            continue
        pmid = str(x.get("pmid", "")).replace("PMID:", "").strip()
        a = abstracts.get(pmid)
        if a is None or _norm(x.get("quote", "")) not in _norm(a["title"] + " " + a["abstract"]):
            continue                                       # never keep a quote that is not in the source
        alt = by_id[x["id"]]
        alt.status = "excluded_by_evidence" if x["found"] == "excluded" else "supported"
        alt.record_id, alt.quote = f"PMID:{pmid}", x.get("quote", "")
    return ver


def deep_check(client, family: str, card: HypothesisCard, ver: Verification, as_of: Optional[str] = None,
               retmax: int = 6, avoid: frozenset = frozenset(), log: Optional[list] = None) -> Verification:
    """A dedicated search per open checklist alternative (intervention + the row's design words), then the
    same check over the new abstracts. Only for strong hypotheses (P(top-k) >= 0.5, before debates)."""
    names = " ".join(i.label for i in card.pico.intervention)
    for alt in [a for a in ver.alternatives if a.source == "checklist" and a.status == "open"]:
        terms = " OR ".join(f'"{t}"' if " " in t else t for t in BY_ID[alt.type].terms)
        pmids = pubmed.search(f"{names} ({terms})", retmax=retmax, as_of=as_of)
        if log is not None:
            log.append({"kind": "search", "alternative": alt.id, "type": alt.type, "pmids": pmids, "as_of": as_of})
        if pmids:
            check(client, family, card, ver, pmids=pmids, avoid=avoid, log=log, only={alt.id})
    return ver
