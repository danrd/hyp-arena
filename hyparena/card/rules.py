"""Deterministic rules over the card (no LLM): validation, admission, claim statuses, the evidence profile and
the known-result check (card spec sections 4a, 7, 8, 10).

The verifier (an LLM) only extracts evidence records with verbatim quotes and their match to the claim's
context; every status and every profile value is computed here from those records."""
from __future__ import annotations

import re
from typing import Iterable, Optional

from hyparena.card.models import (INHERITABLE, RUNGS, UNKNOWN, Admission, Claim, ClaimVerification, Conflict,
                                  DeclaredAlternative, EvidenceProfile, EvidenceRecord, HypothesisCard, Verification)

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
    alternatives = {a.id: a for a in card.declared_alternatives}
    if len(alternatives) != len(card.declared_alternatives) or ids & set(alternatives):
        problems.append("alternative ids must be unique and differ from claim ids")
    rejected = [a for a in card.declared_alternatives if a.stated_as == "rejected"]
    if raw_text is not None:
        text = _norm(raw_text)
        for c in [*card.claims, *rejected]:
            if not c.source_span:
                problems.append(f"{c.id}: source_span is missing")
            elif _norm(c.source_span) not in text:
                problems.append(f"{c.id}: source_span is not a verbatim fragment of the text: {c.source_span!r}")
    for c in [*card.claims, *rejected]:
        if c.relation == "other" and not c.note:
            problems.append(f"{c.id}: relation `other` needs a short note")
        problems += _inheritance_problems(c, card)
    # contrast "mainly X, not Y" (spec 6, 10): the reference and the rejected alternative come together
    referenced = set()
    for c in card.claims:
        ref = c.qualifiers.get("contrast")
        if not ref:
            continue
        referenced.add(ref)
        if ref not in alternatives or alternatives[ref].stated_as != "rejected":
            problems.append(f"{c.id}: qualifiers.contrast must name a declared alternative with stated_as rejected ({ref!r})")
    for a in rejected:
        if a.id not in referenced:
            problems.append(f"{a.id}: a rejected alternative needs a claim with qualifiers.contrast: {a.id}")
    return problems


def pico_value(card: HypothesisCard, key: str) -> str:
    p = card.pico
    return {"species": p.population.label, "strain": p.population.strain, "sex": p.population.sex,
            "age_at_start": p.population.age_at_start if _known(p.population.age_at_start) else p.population.age,
            "comparator": p.comparator.label if _known(p.comparator.label) else p.comparator.type}.get(key, UNKNOWN)


def same_value(key: str, a: str, b: str) -> bool:
    """Qualifier values that name the same thing; species compared by organism ("older adults" = human)."""
    if key == "species":
        sa, sb = species_key(a), species_key(b)
        return bool(sa) and sa == sb
    na, nb = _norm(a).replace("_", " "), _norm(b).replace("_", " ")
    return bool(na) and (na == nb or na in nb or nb in na)


def _inheritance_problems(c, card: HypothesisCard) -> list[str]:
    """Spec 9, 10: only allowed keys, present with the PICO value, only into claims about the intervention."""
    out = []
    for key in c.inherited_from_pico:
        if key not in INHERITABLE:
            out.append(f"{c.id}: {key!r} cannot be inherited from PICO (allowed: {', '.join(INHERITABLE)})")
        elif not same_value(key, c.qualifiers.get(key, ""), pico_value(card, key)):
            out.append(f"{c.id}: inherited {key} must equal the PICO value ({pico_value(card, key)!r})")
    if "species" not in c.inherited_from_pico and _species_unstated(c) and c.role != "analog":
        out.append(f"{c.id}: species {c.qualifiers['species']!r} is not stated in the span; it may only be inherited "
                   f"from PICO into a claim about the intervention (list it in inherited_from_pico), otherwise leave it out")
    if c.inherited_from_pico and not same_intervention(c, card):
        out.append(f"{c.id}: qualifiers are inherited only into claims whose subject is the intervention")
    return out


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
        # the explanation is a mechanism claim or the outcome claim itself (spec 6: in a mechanistic hypothesis
        # the outcome is the explanation, the effect being explained is a premise)
        if outcome is None and not any(c.role == "premise" for c in card.claims):
            missing.append("the effect being explained (outcome or premise claim)")
        if outcome is None and not any(c.role == "mechanism" for c in card.claims):
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
    if record.system in ("ex_vivo", "in_vitro") and _claim_organism(claim):
        return False                                     # ex vivo ≠ in vivo: cells do not support a claim about an organism
    need = claim_endpoint(claim)
    return not (need and record.endpoint not in ("unknown", need))


def _claim_organism(claim) -> bool:
    """The claim is about a living organism: a species qualifier or an organism as the object."""
    return bool(species_key(claim.qualifiers.get("species", ""))) or _species_rung(claim.object.label) is not None


def claim_status(cv: ClaimVerification, claim: Claim) -> str:
    if cv.unresolved or claim.relation == "other":       # `other` is ignored by symbolic checks (spec 5)
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


def contrast_status(x: str, y: str) -> tuple[str, list[str]]:
    """Outcome of a contrast "mainly X, not Y" from the statuses of X and of the rejected alternative Y, in
    order of precedence (spec 7): X refuted or Y supported refute it; a contested Y contests it; an unchecked
    Y leaves a supported X unverified (no support for free)."""
    if x == "refuted" or y == "supported":
        return "refuted", []
    if y == "contested":
        return "contested", []
    if y == "refuted":
        return x, []
    if x == "supported":
        return "unverified", ["contrast_unchecked"]
    return x, []


def _same_context(x: Claim, y: DeclaredAlternative) -> bool:
    """Spec 7: same species, and same strain if both state it (unknown matches)."""
    for key in ("species", "strain"):
        a, b = x.qualifiers.get(key, ""), y.qualifiers.get(key, "")
        if _known(a) and _known(b) and not same_value(key, a, b):
            return False
    return True


def statuses(card: HypothesisCard, ver: Verification) -> dict[str, str]:
    """Status of every verified claim and checked alternative; contrast outcomes follow the contrast rule.
    Also records the inputs on the outcome claim (`contrast`) and the `contrast_unchecked` flag."""
    out = {}
    for cv in ver.claims:
        claim = claim_of(card, cv)
        if claim is not None:
            out[cv.id] = claim_status(cv, claim)
    alternatives = {a.id: a for a in card.declared_alternatives}
    for cv in ver.claims:
        claim = claim_of(card, cv)
        ref = claim.qualifiers.get("contrast") if isinstance(claim, Claim) else None
        if not ref or ref not in alternatives:
            continue
        x = out[cv.id]
        y = out.get(ref, "unverified")
        if not _same_context(claim, alternatives[ref]):
            y = "unverified"                               # Y checked in another context does not decide X
        out[cv.id], flags = contrast_status(x, y)
        cv.contrast = {"alternative": ref, "x_status": x, "y_status": y}
        cv.flags = [f for f in cv.flags if f != "contrast_unchecked"] + flags
    return out


def claim_of(card: HypothesisCard, cv: ClaimVerification):
    """The claim a verification is about: a verifier-added claim, a declared claim or a checked alternative."""
    if cv.added_claim is not None:
        return cv.added_claim
    for c in [*card.claims, *card.declared_alternatives]:
        if c.id == cv.id:
            return c
    return None


# ---- evidence profile (section 8) ----

ORGANISM_PATTERNS = {
    "human": r"\b(?:humans?|patients?|people|adults|participants|volunteers|women|men|subjects)\b",
    "mouse": r"\b(?:mice|mouse|murine)\b", "rat": r"\brats?\b",
    "worm": r"\b(?:elegans|nematodes?|worms?)\b", "fly": r"\b(?:drosophila|flies|fly)\b",
    "yeast": r"\b(?:yeast|cerevisiae)\b"}


def quote_organisms(text: str) -> set[str]:
    """Organisms a sentence names."""
    return {k for k, pat in ORGANISM_PATTERNS.items() if re.search(pat, text or "", flags=re.I)}


def _species_unstated(c) -> bool:
    """The claim has a species that its own span does not name."""
    value = c.qualifiers.get("species", "")
    return bool(species_key(value)) and bool(c.source_span) and species_key(value) not in quote_organisms(c.source_span) \
        and _norm(value) not in _norm(c.source_span)


def mark_inherited(card: HypothesisCard) -> HypothesisCard:
    """Spec 9: a species the span does not state but PICO does, in a claim about the intervention, is inherited:
    mark it (normalizers often copy it without the mark); a species the span names is not. Other unstated
    species stay for validation."""
    for c in [*card.claims, *card.declared_alternatives]:
        if "species" in c.inherited_from_pico and species_key(c.qualifiers.get("species", "")) \
                and not _species_unstated(c):
            c.inherited_from_pico.remove("species")     # the span names it: stated, not inherited
        if "species" not in c.inherited_from_pico and _species_unstated(c) and same_intervention(c, card) \
                and same_value("species", c.qualifiers["species"], pico_value(card, "species")):
            c.inherited_from_pico.append("species")
    return card


def species_key(text: str) -> str:
    """A canonical organism name for comparisons ("" when unknown)."""
    t = _norm(text)
    if not t or t == UNKNOWN:
        return ""
    if t in HUMAN or "human" in t or "patients" in t or "adults" in t or "people" in t:
        return "human"
    for key, words in (("mouse", ("mouse", "mice", "mus musculus", "10090")), ("rat", ("rat", "rats", "rattus", "10116")),
                       ("worm", ("elegans", "worm", "nematode", "6239")), ("fly", ("drosophila", "fly", "flies", "7227")),
                       ("yeast", ("yeast", "cerevisiae", "4932", "559292"))):
        if t in words or any(w in t for w in words if len(w) > 3):
            return key
    return t


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
    ids = {i.id for i in card.pico.intervention if i.id}
    if claim.subject.id and claim.subject.id in ids:
        return True
    labels = set().union(*(_parts(i.label) for i in card.pico.intervention)) if card.pico.intervention else set()
    return bool(labels) and _parts(claim.subject.label) == labels


def _all_claims(card: HypothesisCard, ver: Verification) -> list[tuple[Claim, ClaimVerification]]:
    """Declared and verifier-added claims (alternatives only enter through the contrast rule)."""
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
    status = statuses(card, ver)
    prof = EvidenceProfile()

    # gate: a refuted outcome, mechanism or premise claim filters the hypothesis out
    by_id = {cv.id: cv for cv in ver.claims}
    for c, cv in pairs:
        if c.role in ("outcome", "mechanism", "premise") and status[cv.id] == "refuted" and cv.added_claim is None:
            rec = next((r for r in cv.counterevidence if admissible(r, c)), None)
            alt = by_id.get(cv.contrast.get("alternative", ""))
            if rec is None and alt is not None and cv.contrast.get("y_status") == "supported":
                y = next((r for r in alt.evidence if admissible(r, claim_of(card, alt))), None)
                reason = f"{c.id} refuted by the contrast rule: {alt.id} supported by {y.record_id if y else 'evidence'}"
            else:
                reason = f"{c.id} refuted by {rec.record_id if rec else 'counterevidence'}"
            prof.gate, prof.gate_reason = "filtered", reason
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
    if out is None or cv is None or statuses(card, ver).get(cv.id) != "supported":
        return False
    support = [r for r in cv.evidence if admissible(r, out)]
    return any(r.qualifiers_match.get("intervention_match", "exact") == "exact"
               and all(v in ("yes", "n/a") for k, v in r.qualifiers_match.items() if k != "intervention_match")
               for r in support)


def finalize(card: HypothesisCard, ver: Verification) -> Verification:
    """Fill computed statuses, the evidence profile and the known-result flag."""
    st = statuses(card, ver)
    for cv in ver.claims:
        if cv.id in st:
            cv.status = st[cv.id]
    ver.evidence_profile = evidence_profile(card, ver)
    ver.known_result = known_result(card, ver)
    return ver


def verified_layer_problems(card: HypothesisCard, ver: Verification,
                            sources: Optional[dict[str, str]] = None) -> list[str]:
    """Section 10 checks of the verified layer: statuses carry records; quotes are verbatim in the source."""
    problems = []
    st_all = statuses(card, ver)
    for cv in ver.claims:
        claim = claim_of(card, cv)
        if claim is None:
            problems.append(f"{cv.id}: no such claim")
            continue
        st = st_all[cv.id]
        if cv.contrast:                                   # set by the contrast rule: the alternative carries the records
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
