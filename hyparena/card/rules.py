"""Deterministic rules over the card (no LLM): validation, admission, claim statuses, the evidence profile and
the known-result check (card spec sections 4a, 7, 8, 10).

The verifier (an LLM) only extracts evidence records with verbatim quotes and their match to the claim's
context; every status and every profile value is computed here from those records."""
from __future__ import annotations

import re
from typing import Iterable, Optional

from hyparena.card.models import (RUNGS, UNKNOWN, Admission, Claim, ClaimVerification, Conflict, EvidenceProfile,
                                  EvidenceRecord, HypothesisCard, Verification)

ADMISSIBLE_TYPES = {"A_text", "B_curated", "C_measurement"}
SAME_INTERVENTION = {"exact", "dose_differs", "regimen_differs"}
MAMMALS = {"mouse", "mice", "mus musculus", "rat", "rats", "rattus norvegicus", "dog", "monkey", "macaque",
           "rhesus", "marmoset", "ncbitaxon:10090", "ncbitaxon:10116", "ncbitaxon:9544", "ncbitaxon:9615",
           "ncbitaxon:9483", "mammal", "mammals"}
INVERTEBRATES = {"worm", "worms", "c. elegans", "caenorhabditis elegans", "nematode", "fly", "flies", "drosophila",
                 "drosophila melanogaster", "yeast", "saccharomyces cerevisiae", "ncbitaxon:6239", "ncbitaxon:7227",
                 "ncbitaxon:4932", "ncbitaxon:559292"}     # yeast: grouped with non-mammalian model organisms
HUMAN = {"human", "humans", "homo sapiens", "ncbitaxon:9606", "older adults", "people"}
LIFESPAN_RELATIONS = {"extends_lifespan_in", "shortens_lifespan_in", "no_lifespan_effect_in"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


# ---- validation and admission (sections 4a, 10) ----

def validate_card(card: HypothesisCard, raw_text: Optional[str] = None) -> list[str]:
    """Problems with a declared card; empty when it is valid."""
    problems = []
    outcomes = [c for c in card.claims if c.role == "outcome"]
    if len(outcomes) != 1:
        problems.append(f"exactly one claim must have role outcome (found {len(outcomes)})")
    if len(card.claims) > 8:
        problems.append(f"at most 8 claims (found {len(card.claims)})")
    ids = {c.id for c in card.claims}
    if len(ids) != len(card.claims):
        problems.append("claim ids must be unique")
    for e in card.edges:
        if e.from_ not in ids or e.to not in ids:
            problems.append(f"edge {e.from_} -> {e.to} references a missing claim")
    requires = {}
    for e in card.edges:
        if e.type == "requires":
            requires.setdefault(e.from_, []).append(e.to)
    if _has_cycle(requires):
        problems.append("cycle through `requires` edges")
    if raw_text is not None:
        text = _norm(raw_text)
        for c in card.claims:
            if not c.source_span:
                problems.append(f"{c.id}: source_span is missing")
            elif _norm(c.source_span) not in text:
                problems.append(f"{c.id}: source_span is not a verbatim fragment of the text: {c.source_span!r}")
    for c in card.claims:
        if c.relation == "other" and not c.note:
            problems.append(f"{c.id}: relation `other` needs a short note")
    return problems


def _has_cycle(graph: dict[str, list[str]]) -> bool:
    state: dict[str, int] = {}

    def visit(n):
        if state.get(n) == 1:
            return True
        if state.get(n) == 2:
            return False
        state[n] = 1
        if any(visit(m) for m in graph.get(n, [])):
            return True
        state[n] = 2
        return False

    return any(visit(n) for n in list(graph))


def _known(v: Optional[str]) -> bool:
    return bool(v) and _norm(v) not in (UNKNOWN, "", "none", "n/a")


def admit(card: HypothesisCard) -> Admission:
    """Is this a hypothesis (a decisive experiment can be defined)? Critical fields per type (section 4a)."""
    p = card.pico
    has_population = _known(p.population.taxon) or _known(p.population.label)
    has_endpoint = p.outcome.endpoint != "unknown"
    outcome = card.outcome_claim
    missing = []
    if card.hypothesis_type == "interventional":
        if not p.intervention:
            missing.append("pico.intervention")
        if not has_population:
            missing.append("pico.population")
        if not has_endpoint:
            missing.append("pico.outcome.endpoint")
    elif card.hypothesis_type == "mechanistic":
        if not (p.intervention or (outcome and _known(outcome.subject.label))):
            missing.append("subject entity or intervention")
        if outcome is None:
            missing.append("the effect being explained (outcome claim)")
        if not any(c.role == "mechanism" for c in card.claims):
            missing.append("a mechanism claim")
    elif card.hypothesis_type == "biomarker":
        pred = next((c for c in card.claims if c.relation == "predicts"), None)
        if pred is None:
            missing.append("a `predicts` claim (marker and predicted outcome)")
        if not has_population:
            missing.append("pico.population")
    else:                                                    # observational
        if not (p.intervention or (outcome and _known(outcome.subject.label))):
            missing.append("exposure or variant")
        if outcome is None and not has_endpoint:
            missing.append("outcome")
        if not has_population:
            missing.append("pico.population")
    specificity = sum([has_population, _known(p.population.sex),
                       _known(p.population.age_at_start) or _known(p.population.age),
                       any(_known(i.regimen) for i in p.intervention), _known(p.comparator.type)])
    if not missing:
        return Admission(raw_id=card.raw_id, decision="accepted", context_specificity=specificity)
    nothing_measurable = (not p.intervention and not has_endpoint
                          and (outcome is None or outcome.relation in ("other", "associated_with")))
    if nothing_measurable:
        return Admission(raw_id=card.raw_id, decision="not_a_hypothesis", missing_critical=missing,
                         context_specificity=specificity,
                         reason="no intervention and no measurable outcome: stored as a direction, not ranked")
    return Admission(raw_id=card.raw_id, decision="needs_refinement", missing_critical=missing,
                     context_specificity=specificity)


# ---- claim statuses (section 7) ----

def claim_endpoint(claim: Claim, card: Optional[HypothesisCard] = None) -> Optional[str]:
    """The endpoint a finding must measure to support or refute this claim (None: no endpoint check)."""
    if claim.relation in LIFESPAN_RELATIONS:
        return "lifespan"
    if claim.relation == "improves_healthspan_in":
        return "healthspan"
    if claim.relation in ("changes_biomarker", "predicts"):
        return "biomarker"
    return None


def admissible(record: EvidenceRecord, claim: Claim) -> bool:
    """A record counts for or against a claim only if it is a finding of an admissible epistemic type, its
    context matches (no qualifier marked "no"), it is not retracted, and it measures the claim's endpoint."""
    if record.quote_role != "finding" or record.epistemic_type not in ADMISSIBLE_TYPES or "retracted" in record.flags:
        return False
    if any(v == "no" for k, v in record.qualifiers_match.items() if k != "intervention_match"):
        return False
    need = claim_endpoint(claim)
    return not (need and record.endpoint not in ("unknown", need))


def claim_status(cv: ClaimVerification, claim: Claim) -> str:
    if cv.unresolved:
        return "unresolved"
    support = [r for r in cv.evidence if admissible(r, claim)]
    against = [r for r in cv.counterevidence if admissible(r, claim)]
    if support and against:
        return "contested"
    if support:
        return "supported"
    if against:
        return "refuted"
    return "unverified"


# ---- evidence profile (section 8) ----

def _species_rung(text: str) -> Optional[str]:
    t = _norm(text)
    if not t or t == UNKNOWN:
        return None
    if t in HUMAN or "human" in t or "patients" in t or "adults" in t:
        return "human"
    if t in MAMMALS or any(m in t for m in ("mouse", "mice", "rat ")):
        return "mammals"
    if t in INVERTEBRATES or any(m in t for m in ("elegans", "drosophila", "worm", "fly", "yeast")):
        return "invertebrates"
    return None


def claim_rung(claim: Claim, cv: ClaimVerification) -> str:
    """Rung of a claim: set by the verifier, or from the organism of the claim and the type of its evidence."""
    if cv.rung:
        return cv.rung
    records = cv.evidence + cv.counterevidence
    if records and all(r.system in ("ex_vivo", "in_vitro") for r in records):
        return "cells"
    species = None
    for text in (claim.object.id or "", claim.object.label, claim.qualifiers.get("species", ""),
                 *(r.species for r in records)):
        species = _species_rung(text)
        if species:
            break
    if species == "human":
        endpoint = claim_endpoint(claim)
        return "human_clinical" if endpoint == "lifespan" or claim.relation == "no_lifespan_effect_in" else "human_markers"
    return species or "none"


def _parts(label: str) -> set[str]:
    return {p for p in re.split(r"\s*(?:\+|,|\bplus\b|\band\b|/)\s*", _norm(label)) if p}


def same_intervention(claim: Claim, card: HypothesisCard) -> bool:
    """The claim's subject is the hypothesis's intervention (or the whole combination)."""
    labels = {_norm(i.label) for i in card.pico.intervention}
    ids = {i.id for i in card.pico.intervention if i.id}
    if claim.subject.id and claim.subject.id in ids:
        return True
    subject = _parts(claim.subject.label)
    return bool(labels) and (subject == labels or (len(labels) == 1 and _norm(claim.subject.label) in labels))


def _all_claims(card: HypothesisCard, ver: Verification) -> list[tuple[Claim, ClaimVerification]]:
    by_id = {c.id: c for c in card.claims}
    out = []
    for cv in ver.claims:
        claim = cv.added_claim or by_id.get(cv.id)
        if claim is not None:
            out.append((claim, cv))
    return out


def _grade(records: Iterable[EvidenceRecord]) -> str:
    grades = [r.qualifiers_match.get("intervention_match", "exact") for r in records]
    order = ["exact", "dose_differs", "regimen_differs", "related_compound", "class"]
    return max(grades, key=order.index) if grades else ""


def evidence_profile(card: HypothesisCard, ver: Verification) -> EvidenceProfile:
    pairs = _all_claims(card, ver)
    status = {cv.id: claim_status(cv, c) for c, cv in pairs}
    prof = EvidenceProfile()

    # gate: a refuted outcome, mechanism or premise claim filters the hypothesis out
    for c, cv in pairs:
        if c.role in ("outcome", "mechanism", "premise") and status[cv.id] == "refuted" and cv.added_claim is None:
            rec = next((r for r in cv.counterevidence if admissible(r, c)), None)
            prof.gate, prof.gate_reason = "filtered", f"{c.id} refuted by {rec.record_id if rec else 'counterevidence'}"
            break

    # claims that may set the effect level: the outcome claim, or analog / translation claims with the same intervention
    qualifying = []
    for c, cv in pairs:
        if c.role == "outcome" or (c.role in ("analog", "translation") and same_intervention(c, card)):
            support = [r for r in cv.evidence if admissible(r, c)]
            if c.role != "outcome" and support and _grade(support) not in SAME_INTERVENTION:
                continue                                  # related compounds and classes count only as analogs
            qualifying.append((c, cv, claim_rung(c, cv)))
    supported = [(c, cv, rung) for c, cv, rung in qualifying if status[cv.id] == "supported"]
    if supported:
        top = max(supported, key=lambda x: RUNGS.index(x[2]))
        prof.effect_level = top[2]
        at_level = [x for x in supported if x[2] == prof.effect_level]
        records = [r for c, cv, _ in at_level for r in cv.evidence if admissible(r, c)]
        prof.intervention_match = _grade(records)
        prof.robustness = "replicated" if _independent(records) >= 2 or any(
            r.program and (r.program.sites_with_effect or 0) >= 2 for r in records) else "single"
        if prof.effect_level.startswith("human"):
            if records and all(r.study_type == "observational" for r in records):
                prof.effect_level_note = f"{prof.effect_level} (observational only)"
            elif prof.effect_level == "human_markers" and records and all(r.marker_validation == "exploratory" for r in records):
                prof.effect_level_note = "human_markers (exploratory only)"
    level = RUNGS.index(prof.effect_level)
    prof.effect_contested = sorted({rung for c, cv, rung in qualifying
                                    if status[cv.id] == "contested" and RUNGS.index(rung) > level}, key=RUNGS.index)

    # multi-site program flag, over the qualifying claims
    pos = any(r.program for c, cv, _ in qualifying for r in cv.evidence if admissible(r, c))
    neg = any(r.program for c, cv, _ in qualifying for r in cv.counterevidence if admissible(r, c))
    if pos or neg:
        prof.multi_site_program = {"tested": "yes", "outcome": "mixed" if pos and neg else "positive" if pos else "negative"}

    # mechanism axis
    mech = [status[cv.id] for c, cv in pairs if c.role in ("mechanism", "premise") and cv.added_claim is None]
    if any(s == "refuted" for s in mech):
        prof.mechanism = "refuted"
    elif mech and all(s == "supported" for s in mech):
        prof.mechanism = "supported"
    elif any(s == "supported" for s in mech):
        prof.mechanism = "partial"
    else:
        prof.mechanism = "unverified"

    # conflicts: contested qualifying claims, with both sides
    for c, cv, rung in qualifying:
        if status[cv.id] == "contested":
            prof.conflicts.append(Conflict(rung=rung, **{"for": [r.record_id for r in cv.evidence if admissible(r, c)]},
                                           against=[r.record_id for r in cv.counterevidence if admissible(r, c)],
                                           against_is_program=any(r.program for r in cv.counterevidence)))
    prof.next_step = next_step(prof)
    return prof


def _independent(records: list[EvidenceRecord]) -> int:
    """Independent sources: distinct labs or cohorts; reviews, reanalyses and curated copies of a paper
    already counted do not add."""
    keys = set()
    primary_ids = {r.record_id for r in records if not r.derived_from and not r.linked_pmid}
    for r in records:
        if r.derived_from:
            continue
        if r.linked_pmid and (f"PMID:{r.linked_pmid}" in primary_ids or r.linked_pmid in primary_ids):
            continue
        keys.add(r.lab_or_cohort or r.record_id)
    return len(keys)


def next_step(prof: EvidenceProfile) -> str:
    """Single source at an animal rung → replicate there; a contested higher rung → resolve it; otherwise the
    next rung up (section 8, derived)."""
    if prof.gate == "filtered":
        return ""
    level = prof.effect_level
    if prof.robustness == "single" and level in ("cells", "invertebrates", "mammals"):
        return f"{level}: independent{' (ideally multi-site)' if level == 'mammals' else ''} replication"
    if prof.effect_contested:
        rung = prof.effect_contested[0]
        return f"{rung}: " + ("trial with pre-registered primary outcome" if rung.startswith("human") else "resolve the conflicting results")
    if level == "human_clinical":
        return "human_clinical: independent confirmation"
    nxt = RUNGS[min(RUNGS.index(level) + 1, len(RUNGS) - 1)]
    return f"{nxt}: first test at this rung"


def known_result(card: HypothesisCard, ver: Verification) -> bool:
    """The outcome claim matches an already supported finding exactly (same intervention, context)."""
    out = card.outcome_claim
    cv = next((v for v in ver.claims if out and v.id == out.id), None)
    if out is None or cv is None or claim_status(cv, out) != "supported":
        return False
    support = [r for r in cv.evidence if admissible(r, out)]
    return any(r.qualifiers_match.get("intervention_match", "exact") == "exact"
               and all(v in ("yes", "n/a") for k, v in r.qualifiers_match.items() if k != "intervention_match")
               for r in support)


def finalize(card: HypothesisCard, ver: Verification) -> Verification:
    """Fill computed statuses, the evidence profile and the known-result flag."""
    by_id = {c.id: c for c in card.claims}
    for cv in ver.claims:
        claim = cv.added_claim or by_id.get(cv.id)
        if claim is not None:
            cv.status = claim_status(cv, claim)
    ver.evidence_profile = evidence_profile(card, ver)
    ver.known_result = known_result(card, ver)
    return ver


def verified_layer_problems(card: HypothesisCard, ver: Verification,
                            sources: Optional[dict[str, str]] = None) -> list[str]:
    """Section 10 checks of the verified layer: statuses carry records; quotes are verbatim in the source."""
    problems = []
    by_id = {c.id: c for c in card.claims}
    for cv in ver.claims:
        claim = cv.added_claim or by_id.get(cv.id)
        if claim is None:
            problems.append(f"{cv.id}: no such claim")
            continue
        st = claim_status(cv, claim)
        if st in ("supported", "contested") and not cv.evidence:
            problems.append(f"{cv.id}: {st} without evidence records")
        if st == "refuted" and not cv.counterevidence:
            problems.append(f"{cv.id}: refuted without counterevidence")
        if sources:
            for r in cv.evidence + cv.counterevidence:
                text = sources.get(r.record_id)
                if text is not None and r.quote and _norm(r.quote) not in _norm(text):
                    problems.append(f"{cv.id}: quote not found verbatim in {r.record_id}")
    return problems
