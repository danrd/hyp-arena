"""Normalizer: hypothesis text → declared card (card spec section 9). The LLM parses; code validates the schema,
the closed vocabulary, exactly one outcome claim and that every source_span is verbatim, and asks again with
the problems when something fails."""
from __future__ import annotations

import re
import typing
from typing import Optional

from pydantic import ValidationError

from hyparena.card.llm import ask
from hyparena.card.models import Hallmark, HypothesisCard, Relation
from hyparena.card.canonical import canonicalize
from hyparena.card.rules import anchor_core, core_span_problems, mark_inherited, set_sex_scope, validate_card

TEMPLATE = ("normalize_card", "v6")       # v6 adopted 2026-10-29 by the user's decision, see docs/archive/rules-method.md

# relations an outcome claim can take, with the words that point to them (for the re-parse hint, spec 5)
OUTCOME_RELATIONS = {
    "extends_lifespan_in": "extends increases lifespan longevity survival live longer",
    "shortens_lifespan_in": "shortens decreases lifespan survival mortality",
    "no_lifespan_effect_in": "no effect lifespan survival",
    "slows_aging_in": "slows delays aging ageing age-related changes decline pathology",
    "improves_healthspan_in": "improves healthspan function frailty strength mobility health",
    "changes_biomarker": "changes lowers raises reduces increases biomarker marker level clock blood",
    "predicts": "predicts marker risk outcome mortality",
    "promotes": "promotes causes drives induces increases",
    "suppresses": "suppresses reduces prevents inhibits lowers protects",
    "affects_hallmark": "hallmark senescence autophagy proteostasis mitochondria inflammation",
    "associated_with": "associated linked correlated",
}


def nearest_relations(text: str, k: int = 4) -> list[str]:
    """Vocabulary relations whose cue words overlap most with the claim's note and span."""
    words = set(re.findall(r"[a-z]+", (text or "").lower()))
    score = {r: len(words & set(cues.split())) for r, cues in OUTCOME_RELATIONS.items()}
    return sorted(score, key=lambda r: (-score[r], list(OUTCOME_RELATIONS).index(r)))[:k]


def _closed_fields(value: dict) -> dict:
    """Values outside the closed lists of the stated experiment ("no intervention" for control, say) become "unknown"
    instead of failing the whole card (normalizer-v8 check: one of 30 cards was lost that way). Only these fields."""
    import typing as _t
    from hyparena.card.models import DecisiveExperiment
    e = value.get("decisive_experiment")
    if not isinstance(e, dict):
        return value
    fixed = dict(e)
    for name, field in DecisiveExperiment.model_fields.items():
        allowed = _t.get_args(field.annotation)
        if allowed and all(isinstance(x, str) for x in allowed) and name in fixed and fixed[name] not in allowed:
            fixed[name] = "unknown" if "unknown" in allowed else allowed[-1]
    return {**value, "decisive_experiment": fixed}


ENDPOINT_BY_RELATION = {"changes_biomarker": "biomarker", "increases_expression": "biomarker", "decreases_expression": "biomarker",
                        "improves_healthspan_in": "healthspan", "slows_aging_in": "healthspan", "extends_lifespan_in": "lifespan",
                        "shortens_lifespan_in": "lifespan", "no_lifespan_effect_in": "lifespan"}


def registry_defaults(card: HypothesisCard, raw_text: str) -> list[str]:
    """normalize_card/v10 and later (fresh calibration 2026-11-06: 4 of 44 cards stopped at admission for a field the text
    implies): an unknown endpoint is taken from the outcome claim's relation (for a registry text also promotes/suppresses:
    a health measure of people); an unknown population of a registry text is the registry's conditions, in humans; an AI-role
    span that is not verbatim in the text sets the role to "none". Returns what it filled."""
    filled = []
    registry = raw_text.startswith("A trial registered")
    out = card.outcome_claim
    if card.pico.outcome.endpoint == "unknown" and out is not None:
        ep = ENDPOINT_BY_RELATION.get(out.relation) or ("healthspan" if registry and out.relation in ("promotes", "suppresses") else None)
        if ep:
            card.pico.outcome.endpoint = ep
            filled.append(f"endpoint {ep} from relation {out.relation}")
    pop = card.pico.population
    if registry and pop.label in ("", "unknown") and not pop.taxon:
        m = re.search(r"^Conditions:\s*(.+)$", raw_text, re.M)
        pop.label, pop.taxon = (m.group(1).strip()[:120] if m else "trial participants"), "NCBITaxon:9606"
        pop.span = m.group(1).strip()[:120] if m else ""
        filled.append("population from the registry conditions")
    if card.ai_role != "none" and (not card.ai_role_span or re.sub(r"\s+", " ", card.ai_role_span).strip().lower()
                                   not in re.sub(r"\s+", " ", raw_text).lower()):
        card.ai_role, card.ai_role_span = "none", ""
        filled.append("ai_role none: span not in the text")
    return filled


def _problems(value: dict, raw_text: str, card_id: str, core: bool = False, v15: bool = False) -> tuple[Optional[HypothesisCard], list[str]]:
    value = _closed_fields(value)
    try:
        card = HypothesisCard.model_validate({**value, "id": card_id, "raw_id": card_id})
    except ValidationError as e:
        return None, [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()[:12]]
    extra = []
    if v15:
        v15_prepare(card)                               # premises off the chain before roles are derived
        extra = primary_from_registry(card, raw_text)   # the main outcome is the registry's primary outcome (code)
    derive_roles(card)                                  # v13: `role` from `primary` and `stated_as` (no-op before v13)
    set_sex_scope(card, raw_text)                       # `any` from the words "at least one sex" when the model left it out
    canonicalize(card)                                  # dose and age in one wording (L1.8)
    problems = validate_card(card, raw_text, max_claims=12 if v15 else 8) + (core_span_problems(card, raw_text) if core else [])
    if v15:
        problems += extra + v15_problems(card)
    return mark_inherited(card), problems


def normalize(client, family: str, raw_text: str, card_id: str, log: Optional[list] = None,
              rounds: int = 3, version: Optional[str] = None) -> tuple[Optional[HypothesisCard], list[str]]:
    """(card or None, remaining problems). An outcome claim with relation `other` gets one re-parse with a hint
    listing the nearest vocabulary relations (spec 5); if it stays `other`, admission flags it."""
    variables = {"text": raw_text, "relations": ", ".join(typing.get_args(Relation)),
                 "hallmarks": ", ".join(typing.get_args(Hallmark)), "hint": ""}
    vnum = int((version or TEMPLATE[1]).lstrip("v") or 0)
    core = vnum >= 12                                   # normalize_card/v12: spans for the core fields, checked like claims
    v15 = vnum >= 15                                    # normalize_card/v15: chain and premises, main factor, code checks
    run = lambda v: ask(client, role="normalize_card", family=family, template=TEMPLATE[0], version=version or TEMPLATE[1],
                        variables=v, validate=lambda x: _problems(x, raw_text, card_id, core, v15)[1], rounds=rounds, log=log)[0]
    value = run(variables)
    if value is None:
        return None, ["no valid JSON from the normalizer"]
    first, _ = _problems(value, raw_text, card_id, v15=v15)
    out = first.outcome_claim if first is not None else None
    if out is not None and out.relation == "other":
        near = nearest_relations(f"{out.note} {out.source_span} {out.object.label}")
        hint = (f'In an earlier parse the outcome claim ("{out.source_span}") got relation "other" (note: '
                f'"{out.note or "none"}"). Check whether one of these relations fits it: {", ".join(near)}. '
                f'Keep "other" only if none of them states what the text says.')
        again = run({**variables, "hint": hint})
        if again is not None and _problems(again, raw_text, card_id, v15=v15)[0] is not None:
            value = again
    card, problems = _problems(value, raw_text, card_id, v15=v15)   # core spans are settled by anchor_core below, not by dropping
    if card is not None and problems:                  # drop claims whose span is not verbatim, keep the rest
        bad = {p.split(":")[0] for p in problems if "source_span" in p}
        if bad and len(bad) < len(card.claims):
            card.claims = [c for c in card.claims if c.id not in bad]
            card.edges = [e for e in card.edges if e.from_ not in bad and e.to not in bad]
            problems = validate_card(card, raw_text, max_claims=12 if v15 else 8) + (v15_problems(card) if v15 else [])
    if card is not None and vnum >= 10:
        registry_defaults(card, raw_text)
    if card is not None and vnum >= 13:
        v13_code_fields(card, raw_text)
    if card is not None and core:
        anchor_core(card, raw_text)
    return card, problems


# ---- union of two parses (method v3.9, user decision 2026-11-11) -------------------------------------------------------
# Two parses of the same text at temperature 0 still differ (H49: the first parse missed the mechanism steps the second
# wrote, both with verbatim spans). The card is the union of the parses: every claim either parse wrote with a verbatim span,
# matched by (subject, relation, object, and the measure where the object is the organism); the first parse keeps its ids and its outcome claim; a missing field of the
# experiment or the PICO is taken from the second. The agreement of the parses is kept as the card's stability.

ORGANISM_RELATIONS = ("improves_healthspan_in", "extends_lifespan_in", "shortens_lifespan_in", "slows_aging_in",
                      "no_lifespan_effect_in")


def _claim_key(c) -> tuple:
    """Subject, relation, object; the measure only where the object is the organism (there the measure is what changes;
    elsewhere it restates the object: "body composition" / "bioelectrical impedance analysis")."""
    norm = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())
    measure = norm(c.qualifiers.get("measure")) if c.relation in ORGANISM_RELATIONS else ""
    return (norm(c.subject.label), c.relation, norm(c.object.label), measure)


def _unknown(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip().lower() in ("", "unknown"))


def union_cards(a: HypothesisCard, b: HypothesisCard, raw_text: str) -> tuple[HypothesisCard, dict]:
    card = a.model_copy(deep=True)
    keys = {_claim_key(c): c.id for c in card.claims}
    idmap, added = {}, []
    used = {c.id for c in card.claims}
    n = max([int(m.group(1)) for c in card.claims if (m := re.fullmatch(r"c(\d+)", c.id))] or [0])
    for c in b.claims:
        k = _claim_key(c)
        if k in keys:
            idmap[c.id] = keys[k]
            continue
        n += 1
        while f"c{n}" in used:
            n += 1
        nc = c.model_copy(deep=True)
        nc.id = f"c{n}"
        used.add(nc.id)
        if nc.role == "outcome":                       # one outcome claim: the first parse's
            nc.role = "premise"
            if nc.primary:
                nc.primary = False
        card.claims.append(nc)
        keys[k] = nc.id
        idmap[c.id] = nc.id
        added.append(nc.id)
    have = {(e.from_, e.to, e.type) for e in card.edges}
    for e in b.edges:
        f, t = idmap.get(e.from_), idmap.get(e.to)
        if f and t and (f, t, e.type) not in have:
            card.edges.append(e.model_copy(update={"from_": f, "to": t}))
            have.add((f, t, e.type))
    filled, conflicts = [], []
    for part in ("decisive_experiment",):
        pa, pb = getattr(card, part), getattr(b, part)
        for field in type(pa).model_fields:
            va, vb = getattr(pa, field), getattr(pb, field)
            if _unknown(va) and not _unknown(vb):
                setattr(pa, field, vb)
                filled.append(f"{part}.{field}")
            elif not _unknown(va) and not _unknown(vb) and va != vb:
                conflicts.append(f"{part}.{field}: {va!r} / {vb!r}")
    pop_a, pop_b = card.pico.population, b.pico.population
    for field in type(pop_a).model_fields:
        if _unknown(getattr(pop_a, field)) and not _unknown(getattr(pop_b, field)):
            setattr(pop_a, field, getattr(pop_b, field))
            filled.append(f"pico.population.{field}")
    alt_keys = {_claim_key(x) for x in card.declared_alternatives}
    for x in b.declared_alternatives:
        if _claim_key(x) not in alt_keys:
            card.declared_alternatives.append(x.model_copy(deep=True))
            alt_keys.add(_claim_key(x))
    shared = len({_claim_key(c) for c in a.claims} & {_claim_key(c) for c in b.claims})
    total = len({_claim_key(c) for c in a.claims} | {_claim_key(c) for c in b.claims})
    stability = {"claims": [len(a.claims), len(b.claims)], "shared": shared, "jaccard": round(shared / total, 3) if total else 1.0,
                 "added_from_second": added, "filled_from_second": filled, "conflicts": conflicts}
    return card, stability


def normalize_union(client, family: str, raw_text: str, card_id: str, log: Optional[list] = None, runs: int = 2,
                    version: Optional[str] = None) -> tuple[Optional[HypothesisCard], list[str], dict]:
    """`runs` independent parses united (runs = 1: a single parse). Returns (card, problems, stability)."""
    parses = [normalize(client, family, raw_text, card_id, log=log, version=version) for _ in range(max(1, runs))]
    good = [(c, p) for c, p in parses if c is not None]
    if not good:
        return None, parses[0][1], {"parses": len(parses), "valid": 0}
    card, problems = good[0]
    stab = {"parses": len(parses), "valid": len(good)}
    for other, _ in good[1:]:
        card, s = union_cards(card, other, raw_text)
        stab.update(s)
    if len(good) > 1:
        v15 = int((version or TEMPLATE[1]).lstrip("v") or 0) >= 15
        if v15:
            v15_prepare(card)
            primary_from_registry(card, raw_text)
        problems = validate_card(card, raw_text, max_claims=12 if v15 else 8) + (v15_problems(card) if v15 else [])
        if int((version or TEMPLATE[1]).lstrip("v") or 0) >= 13:
            stab["deduplicated"] = dedupe_claims(card)  # near-duplicates the union added (card benchmark 2026-11-12)
            n1, n2 = (stab.get("claims") or [0, 0])[:2]
            added = set(stab.get("added_from_second") or [])           # a removed near-duplicate from the second parse was
            sh = stab.get("shared", 0) + len(added & set(stab["deduplicated"]))   # the same claim as one of the first
            stab["jaccard_after_dedupe"] = round(sh / (n1 + n2 - sh), 3) if n1 + n2 - sh > 0 else 1.0
            derive_roles(card)
            card.decisive_experiment.duration_class = "unknown"
            v13_code_fields(card, raw_text)             # fields the second parse filled (duration, primary outcomes)
        if int((version or TEMPLATE[1]).lstrip("v") or 0) >= 12:
            anchor_core(card, raw_text)                 # a span the first parse lacked may have come from the second
    return card, problems, stab


# ---- normalize_card/v13 (2026-11-12, user decisions of the card walkthrough) ------------------------------------------------
PRE_OUTCOME = ("delivery", "engagement", "pathway", "effect", "step")
CONTROL_BY_COMPARATOR = {"placebo": "placebo", "sham": "placebo", "active": "active", "usual_care": "usual_care",
                         "no_intervention": "none"}


def derive_roles(card: HypothesisCard) -> None:
    """v13 cards state `primary` and `stated_as`; `role` (read by the rules of v1-v3) is derived from them: the primary outcome
    is `outcome`, an analogy `analog`, a claimed step before the outcome `mechanism`, everything else `premise`."""
    if not any(c.primary is not None or c.stated_as for c in card.claims):
        return                                          # a card before v13
    outs = [c for c in card.claims if c.link == "outcome"]
    prim = [c for c in outs if c.primary] or outs[:1] or [c for c in card.claims if c.stated_as != "analogy"][:1]
    main = prim[0] if prim else None
    for c in card.claims:
        c.primary = c is main
        c.role = ("outcome" if c is main else "analog" if c.stated_as == "analogy"
                  else "mechanism" if c.link in PRE_OUTCOME and c.stated_as != "known" else "premise")


def duration_class(text: str) -> str:
    """weeks / months / years / decades from a duration written in the text, by its length in days (the longest one named):
    under 90 days weeks, under 2 years months, under 10 years years, else decades (v13; the normaliser before v13 chose the
    class itself and was not consistent: 12 weeks "weeks" but 24 weeks "months"); unknown when no duration is written."""
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "eleven": 11, "twelve": 12, "eighteen": 18, "twenty": 20, "twenty-four": 24, "thirty": 30, "thirty-six": 36}
    t = re.sub(r"\b(" + "|".join(sorted(words, key=len, reverse=True)) + r")\b", lambda m: str(words[m.group(1)]), (text or "").lower())
    nums = [(float(n), u) for n, u in re.findall(r"(\d+(?:\.\d+)?)\s*-?\s*(day|week|month|year)", t)]
    if not nums:
        return "unknown"
    days = max(n * {"day": 1, "week": 7, "month": 30.4, "year": 365}[u] for n, u in nums)
    return "weeks" if days < 90 else "months" if days < 730 else "years" if days < 3650 else "decades"


def registry_design(raw_text: str) -> dict:
    """The design and arm lines the text builder writes for a registry trial (scripts/benchmark_run._ctgov_design), as fields."""
    out = {}
    m = re.search(r"^Design:\s*(.+)$", raw_text, re.M)
    if m:
        d = m.group(1).lower()
        out["allocation"] = "randomized" if "non-randomized" not in d and "randomized" in d else (
            "non_randomized" if "non-randomized" in d else "unknown")
        mm = re.search(r"masking (\w+)(?: \(([^)]*)\))?", d)
        out["masking"] = mm.group(1) if mm else "unknown"
        out["masked"] = [x.strip() for x in mm.group(2).split(",")] if mm and mm.group(2) else []
        model = re.search(r"\b(parallel|crossover|factorial|single group|sequential)\b", d)
        out["model"] = model.group(1) if model else "unknown"
        pp = re.search(r"primary purpose ([a-z_ ]+)", d)
        out["purpose"] = pp.group(1).strip() if pp else "unknown"
    m = re.search(r"^Arms:\s*(.+)$", raw_text, re.M)
    if m:
        out["arms"] = [{"label": a.group(1).strip(), "type": a.group(2).strip()}
                       for a in re.finditer(r"(?:^|; )((?:(?!; )[^()])+?) \((experimental|active comparator|placebo comparator|"
                                            r"sham comparator|no intervention|other)\)", m.group(1))]
    m = re.search(r"^Planned enrollment:\s*(\d+)", raw_text, re.M)
    if m:
        out["planned_enrollment"] = int(m.group(1))
    return out


def author_refs(raw_text: str) -> list[str]:
    pm = [f"PMID:{x}" for x in re.findall(r"PMID[:\s]*(\d{6,8})", raw_text, re.I)]
    doi = [f"doi:{x.rstrip('.,;)')}" for x in re.findall(r"\b(10\.\d{4,9}/[^\s\"<>]+)", raw_text)]
    return list(dict.fromkeys(pm + doi))


def v13_code_fields(card: HypothesisCard, raw_text: str) -> None:
    """Fields v13 leaves to code: the experiment's control from the comparator (one vocabulary), its duration class from the
    stated duration, the joined primary outcomes (several are equal, rules_v3.outcome_group), the registry design fields,
    the references the text names."""
    e, p = card.decisive_experiment, card.pico
    e.control = CONTROL_BY_COMPARATOR.get(p.comparator.type, e.control)
    if e.duration_class == "unknown":
        e.duration_class = duration_class(f"{e.duration} {p.time}")
    if e.primary_outcomes and _unknown(e.primary_outcome):
        e.primary_outcome = "; ".join(e.primary_outcomes)
    if _unknown(e.endpoint):
        e.endpoint = p.outcome.metric
    e.registry = registry_design(raw_text)
    p.population.age_class = age_class(p.population.age_at_start, p.population.taxon)
    if e.n_planned is None and e.registry.get("planned_enrollment"):
        e.n_planned = e.registry["planned_enrollment"]
    card.author_refs = author_refs(raw_text)


def _target(c) -> str:
    return (c.qualifiers or {}).get("measure") or c.object.label if c.relation in ORGANISM_RELATIONS else c.object.label


def _overlap(a: str, b: str) -> float:
    ta, tb = set(re.findall(r"\w+", (a or "").lower())), set(re.findall(r"\w+", (b or "").lower()))
    return len(ta & tb) / min(len(ta), len(tb)) if ta and tb else 0.0


def dedupe_claims(card: HypothesisCard) -> list[str]:
    """v13 (card benchmark 2026-11-12: the union of two parses wrote 287 claims for Argon's 166): a later claim is a duplicate
    of an earlier one when both sit at the same link, their targets (the object, or the measure where the object is the
    organism) share at least half of the shorter one's words, and so do their subjects (two components of one programme with
    the same outcome stay apart). The earlier claim is kept (the first parse's), the primary one always; edges and contrast
    references move to the kept claim. Returns the ids removed."""
    keep, removed, alias = [], [], {}
    for c in sorted(card.claims, key=lambda c: (not c.primary, card.claims.index(c))):
        twin = next((k for k in keep if k.link == c.link and _overlap(_target(k), _target(c)) >= 0.5
                     and _overlap(k.subject.label, c.subject.label) >= 0.5), None)
        if twin is None:
            keep.append(c)
        else:
            removed.append(c.id)
            alias[c.id] = twin.id
    if removed:
        order = {c.id: i for i, c in enumerate(card.claims)}
        card.claims = sorted(keep, key=lambda c: order[c.id])
        seen, edges = set(), []
        for e in card.edges:
            f, t = alias.get(e.from_, e.from_), alias.get(e.to, e.to)
            if f != t and (f, t, e.type) not in seen:
                seen.add((f, t, e.type))
                edges.append(e.model_copy(update={"from_": f, "to": t}))
        card.edges = edges
        for c in card.claims:
            ref = (c.qualifiers or {}).get("contrast")
            if ref in alias:
                c.qualifiers["contrast"] = alias[ref]
    return removed


# ---- normalize_card/v15 (docs/system/card.md, "Звенья: как определяется тип"; 2026-11-13) ---------------------------------
STEP_LEVELS = {"engagement": {"molecule"}, "pathway": {"molecule", "cell"}, "effect": {"tissue", "organ", "organism"}}
_STOP = {"the", "and", "with", "for", "from", "into", "older", "adults", "adult", "elderly", "people", "patients", "human",
         "humans", "mice", "mouse", "level", "levels", "of", "in", "on", "by", "a", "an", "to"}
MESH_AGE = [(80, "Aged, 80 and over"), (65, "Aged"), (45, "Middle Aged"), (19, "Adult"), (13, "Adolescent"), (2, "Child"),
            (0, "Infant")]
AGE_WORDS = [(r"\b(oldest[- ]old|octogenarian|nonagenarian|over 80|80\+)", ["Aged, 80 and over"]),
             (r"\bmiddle[- ]aged?\b", ["Middle Aged"]),
             (r"\b(elderly|older (adults?|people|persons|individuals|women|men)|aged|seniors?|old age|geriatric)\b", ["Aged"]),
             (r"\byoung adults?\b", ["Adult"])]


# Life phases of laboratory mice (Flurkey, Currer, Harrison 2007, "Mouse models in aging research", The Mouse in Biomedical
# Research, 2nd ed., vol. 3, sec. II.C; checked 2026-11-14 against the authors' manuscript, kept in longevity-kg/reference):
# young adult 3 to about 6 months; middle age 10 to 14-15 months; old from 18 months (upper limit 22-26 by genotype).
# Ages between the phases get their neighbours' names. Reference only, not scored.
MOUSE_PHASES = [(18, "old (mouse)"), (15, "between middle age and old (mouse)"), (10, "middle-aged (mouse)"),
                (6, "between young adult and middle age (mouse)"), (3, "young adult (mouse)"), (0, "immature (mouse)")]
_ANIMAL_TAXA = {"NCBITaxon:10090": "mouse", "NCBITaxon:10116": "rat"}


def _animal_age_class(t: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to|–)?\s*(\d+(?:\.\d+)?)?\s*(month|mo\b|week|wk|day)", t)
    if not m:
        words = [("old (mouse)", r"\b(old|aged|elderly|late[- ]life)\b"), ("middle-aged (mouse)", r"middle[- ]aged?"),
                 ("young adult (mouse)", r"\b(young|young adult)\b"), ("immature (mouse)", r"\b(juvenile|weanling|pup)s?\b")]
        return next((c for c, p in words if re.search(p, t)), "")
    v = float(m.group(1)) * {"month": 1, "mo": 1, "week": 12 / 52, "wk": 12 / 52, "day": 12 / 365}[m.group(3)]
    return next(c for bound, c in MOUSE_PHASES if v >= bound)


def age_class(text: str, taxon: Optional[str] = None) -> str:
    """The MeSH age groups a stated age covers (people only; animals get their own scale later): a number or a range of
    years gives the groups from its lower bound to its upper one ("or older", "+", ">=" up to 80 and over); words map by a
    short list (elderly, older adults -> Aged); "" when nothing fits."""
    t = (text or "").lower()
    if taxon == "NCBITaxon:10090":
        return _animal_age_class(t) if t and t != "unknown" else ""
    if taxon and taxon not in ("NCBITaxon:9606",):
        return ""
    if not t or t == "unknown":
        return ""
    nums = [int(x) for x in re.findall(r"(\d{1,3})\s*(?:-|to|–|\s)?\s*(?=(?:\d{1,3}\s*)?(?:years?|yrs?|y\b|\+|or older|and older|and over|or over))", t)]
    nums += [int(x) for x in re.findall(r"(?:>=|≥|over|above|aged)\s*(\d{1,3})", t)]
    nums = [n for n in nums if n < 120]
    if nums:
        lo, hi = min(nums), max(nums)
        if re.search(r"or older|and older|and over|or over|\+|>=|≥|over|above", t):
            hi = 120
        groups = [g for bound, g in MESH_AGE if bound <= hi and (bound >= lo or bound == max(b for b, _ in MESH_AGE if b <= lo))]
        return "; ".join(dict.fromkeys(reversed(groups)))
    for pat, gs in AGE_WORDS:
        if re.search(pat, t):
            return "; ".join(gs)
    return ""


def _toks(s: str) -> set:
    return {w[:6] for w in re.findall(r"[a-z0-9]{3,}", (s or "").lower())} - {w[:6] for w in _STOP}


def v15_prepare(card: HypothesisCard) -> None:
    """A premise is off the chain (no link); a chain claim without a part is chain when it has a link."""
    for c in card.claims:
        if c.part is None:
            c.part = "chain" if c.link else "premise"
        if c.part == "premise":
            c.link = None
            c.primary = False


def primary_from_registry(card: HypothesisCard, raw_text: str) -> list[str]:
    """For a registry text the main outcome is the claim matching the registry's primary outcome by words (the first primary
    outcome that has such a claim). A primary outcome with no matching outcome claim is sent back to the model."""
    m = re.search(r"^Primary outcomes:\s*(.+)$", raw_text, re.M)
    if not m:
        return []
    regs = [re.sub(r"\([^)]*\)\s*$", "", x).strip() for x in m.group(1).split(";") if x.strip()]
    outs = [c for c in card.claims if c.link == "outcome" and c.part != "premise"]
    problems, main = [], None
    for r in regs:
        rt = _toks(r) - {"assess", "measur", "change", "baseli", "score", "total"}
        best = max(outs, key=lambda c: len(rt & _toks(f"{c.object.label} {c.qualifiers.get('measure', '')}")), default=None)
        if best is not None and rt & _toks(f"{best.object.label} {best.qualifiers.get('measure', '')}"):
            main = main or best
        else:
            problems.append(f"the registry primary outcome {r!r} has no outcome claim: write one (part chain, link outcome, "
                            f"its measure as the object or in qualifiers.measure) with a source_span that states it")
    if main is not None:
        for c in card.claims:
            c.primary = c is main
    return problems


def v15_problems(card: HypothesisCard) -> list[str]:
    """Checks of normalize_card/v15, sent back to the model like the span checks: English labels; part and link agree; a chain
    claim starts from the main factor, the intervention or an earlier step; the link fits the level (docs/system/card.md)."""
    out = []
    if not card.main_factor or not str(card.main_factor.get("label") or "").strip():
        out.append("main_factor is missing: name the thing whose consequences the hypothesis states")
    other = [("main_factor", (card.main_factor or {}).get("label", "")), ("topic", (card.topic or {}).get("label", "")),
             ("population.condition", card.pico.population.condition)] + \
            [(f"decisive_experiment.arms[{i}]", a) for i, a in enumerate(card.decisive_experiment.arms)]
    out += [f"{name}: write it in English" for name, v in other if re.search(r"[а-яА-ЯёЁ]", v or "")]
    cond = card.pico.population.condition or ""
    if cond.count(";") >= 2 or cond.count(",") >= 3:
        out.append("population.condition: write the state the participants are selected for as one short phrase (who is "
                   "enrolled), not the list of the registry's Conditions")
    roots = _toks((card.main_factor or {}).get("label", "")) | set().union(*[_toks(i.label) for i in card.pico.intervention] or [set()])
    seen = set(roots)
    for c in card.claims:
        labels = f"{c.subject.label} {c.object.label} {c.qualifiers.get('measure', '')}"
        if re.search(r"[а-яА-ЯёЁ]", labels):
            out.append(f"{c.id}: write subject, object and measure labels in English (the source_span stays in the text's language)")
        if c.part == "premise" and c.link:
            out.append(f"{c.id}: a premise has no link")
        if c.part == "chain" and not c.link:
            out.append(f"{c.id}: a chain claim needs a link")
        if c.part == "chain" and c.link != "outcome" and roots and not (_toks(c.subject.label) & seen):
            out.append(f"{c.id}: part chain, but its subject ({c.subject.label!r}) is neither the main factor, the intervention nor "
                       f"the object of an earlier chain claim: make it a premise or write the step it follows from")
        allowed = STEP_LEVELS.get(c.link or "")
        if allowed and c.level and c.level not in allowed:
            out.append(f"{c.id}: link {c.link} with level {c.level}: an engagement acts on a named molecule, a pathway (cellular "
                       f"process) is inside cells, an effect is a state of a tissue, organ or body system - fix the link or the level")
        if c.part == "chain":
            seen |= _toks(c.object.label) | _toks(c.qualifiers.get("measure", ""))
        mf = _toks((card.main_factor or {}).get("label", ""))
        if c.part == "premise" and mf and _toks(c.subject.label) and _toks(c.subject.label) <= mf:
            out.append(f"{c.id}: its subject is the main factor, so it is a chain claim (a known result of the main factor is an "
                       f"outcome or a step with stated_as known), not a premise")
    steps = [c for c in card.claims if c.link == "step"]
    if len(steps) > 4:
        out.append(f"{len(steps)} steps before the outcomes: keep at most 4 that the reasoning of the text needs (merge the rest)")
    return out
