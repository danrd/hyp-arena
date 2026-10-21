"""Typed proximity from the card (card spec 8b): similarity over resolved entity identifiers in PICO and over
claims in the closed relation vocabulary; the output is a relation type, not one number.

| type | rule here |
|---|---|
| duplicate | same intervention, species, explained effect (relation and object of the outcome; for a mechanistic hypothesis its premise), same direction, same context and same mechanism claims |
| variant | as duplicate, but the context differs (sex, age at start, strain, dose or regimen, route, comparator, measure), or only one of the two states a mechanism |
| competitor | same intervention and effect, both state mechanisms, the mechanisms differ |
| contradiction | the same claim triple (subject, relation family, object, species) with opposite direction, in any claims of the two cards |
| analog | different interventions sharing a ChEMBL mechanism target and an ATC level-4 class (sirolimus, everolimus, temsirolimus: FKBP1A + L04AH / L01EG); not tacrolimus or pimecrolimus, which bind FKBP1A too but inhibit calcineurin (L04AD, D11AH) |
| analog_weak | a shared mechanism target, and one of the two has no ATC code; or, when at least one of the two has no ChEMBL mechanism target, a narrow shared ChEBI class (most specific common is_a ancestor of at most `chebi.MAX_DESCENDANTS` members: quercetin and fisetin, 7-hydroxyflavonol, 41) |
| mechanism_neighbour | different interventions whose own claims act on the same hallmark or the same molecular node |

A pair can carry several types (a competitor in another context is also a variant). Pairs are found through
buckets (same intervention, same claim triple, same target or class, same node), not by comparing every pair,
so pools of thousands of cards are cheap.

Entities without identifiers (classes, diets, procedures, genes, processes) match by name. With an embedder,
names that are near-synonyms are merged first (`name_aliases`: SapBERT, cosine >= 0.80 and the same numbers in
both names, so omega-3 / omega-6 and mTORC1 / mTORC2 stay apart); a relation that rests on such a merge carries
`approximate` with the merged names (spec 8b: "fall back to embedding similarity, marked as an approximation"),
and an approximate duplicate gets the type `duplicate_approx` (shown to the expert and judges, never removed). Limits: refinement siblings (`parent_id`) are not
linked yet; mechanisms worded differently match only through the same object entity, a merged name or a
hallmark. Applied to supported edges of a knowledge graph the same keys would give novelty (spec 8b); the
graph does not exist yet."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Callable, Iterable, Optional

from hyparena.card.models import UNKNOWN, Claim, HypothesisCard
from hyparena.card.rules import same_intervention, species_key, strain_key
from hyparena.tools import compounds as cp

# relation → (family, direction): the same family with another direction is a contradiction
FAMILY = {"extends_lifespan_in": ("lifespan", 1), "shortens_lifespan_in": ("lifespan", -1),
          "no_lifespan_effect_in": ("lifespan", 0), "slows_aging_in": ("aging", 1),
          "improves_healthspan_in": ("healthspan", 1), "promotes": ("causal", 1), "suppresses": ("causal", -1),
          "inhibits": ("target", -1), "activates": ("target", 1), "increases_expression": ("expression", 1),
          "decreases_expression": ("expression", -1), "changes_biomarker": ("biomarker", 1), "predicts": ("predicts", 1),
          "associated_with": ("association", 1), "affects_hallmark": ("hallmark", 1), "part_of": ("part_of", 1),
          "translates_to": ("translates_to", 1)}
ORGANISM = {"extends_lifespan_in", "shortens_lifespan_in", "no_lifespan_effect_in", "slows_aging_in", "improves_healthspan_in"}
MOLECULAR = {"inhibits", "activates", "increases_expression", "decreases_expression", "part_of", "affects_hallmark"}
NEGATED = {"no_effect", "none", "no", "not", "no effect"}
DOWN = {"decrease", "down", "lower", "reduce", "reduces", "decreases"}
TYPES = ("duplicate", "duplicate_approx", "contradiction", "competitor", "variant", "analog", "analog_weak",
         "mechanism_neighbour")
ALIAS_THRESHOLD = 0.80                       # cosine for merging unresolved names (SapBERT; see name_aliases)


def _norm(s: Optional[str]) -> str:
    s = re.sub(r"\s+", " ", (s or "").lower().replace("_", " ")).strip()
    return "" if s in (UNKNOWN, "n/a", "none") else s


class Names:
    """Name keys of unresolved entities, with near-synonyms merged (`aliases`: name key → canonical key); records
    which original names a card used for each merged key."""

    def __init__(self, aliases: Optional[dict] = None):
        self.aliases = aliases or {}
        self.merged = defaultdict(set)

    def key(self, name: str) -> str:
        k = cp.key(name)
        c = self.aliases.get(k, k)
        if c != k:
            self.merged[c].add(k)
        return c


def entity_key(entity, names: Optional[Names] = None) -> frozenset:
    """Identifiers when resolved (a combination "CHEBI:a+CHEBI:b" → both), else the normalized names of its parts."""
    if entity.id:
        return frozenset(entity.id.split("+"))
    names = names or Names()
    return frozenset(names.key(p) for p in cp.split(entity.label) if cp.key(p)) or frozenset({names.key(entity.label)})


def intervention_key(card: HypothesisCard, names: Optional[Names] = None) -> frozenset:
    items = card.pico.intervention
    if items and all(i.id for i in items):
        return frozenset(i.id for i in items)
    names = names or Names()
    return frozenset(names.key(p) for i in items for p in (cp.split(i.label) or [i.label]) if cp.key(p))


def direction(claim: Claim) -> int:
    fam, d = FAMILY.get(claim.relation, ("", 1))
    q = _norm(claim.qualifiers.get("direction"))
    if q in NEGATED:
        return 0
    if claim.relation in ("changes_biomarker", "affects_hallmark", "associated_with") and q in DOWN:
        return -1
    return d


def claim_species(claim: Claim, card: HypothesisCard) -> str:
    s = species_key(claim.qualifiers.get("species", ""))
    if not s and claim.relation in ORGANISM:
        s = species_key(claim.object.label) or species_key(claim.object.id or "")
    return s


def triple(claim: Claim, card: HypothesisCard, names: Optional[Names] = None) -> Optional[tuple]:
    """(subject, relation family, object, species), direction left out; None for `other`."""
    if claim.relation not in FAMILY:
        return None
    obj = frozenset({claim_species(claim, card)}) if claim.relation in ORGANISM else entity_key(claim.object, names)
    return (entity_key(claim.subject, names), FAMILY[claim.relation][0], obj, claim_species(claim, card))


@dataclass
class Signature:
    id: str
    intervention: frozenset
    species: str
    effect: Optional[frozenset]              # explained effect: triples with direction; None when undefined
    explanation: frozenset                   # mechanism claims (for a mechanistic card: its outcome and mechanisms)
    context: tuple
    triples: dict = field(default_factory=dict)    # triple → (claim id, direction)
    targets: frozenset = frozenset()         # analog keys: "target:<ChEMBL id>", "atc4:<code>", "class:<ChEBI id>|<label>"
    nodes: frozenset = frozenset()           # hallmarks and molecular objects of the intervention's own claims
    merged: dict = field(default_factory=dict)     # canonical name key → the card's own names merged into it


def _context(card: HypothesisCard, out: Optional[Claim]) -> tuple:
    p = card.pico
    q = out.qualifiers if out else {}
    return (_norm(p.population.sex) or _norm(q.get("sex")), _norm(p.population.age_at_start) or _norm(q.get("age_at_start")),
            strain_key(_norm(p.population.strain) or _norm(q.get("strain"))),
            tuple(sorted(_norm(i.regimen) for i in p.intervention)), tuple(sorted(_norm(i.route) for i in p.intervention)),
            _norm(p.comparator.type), _norm(q.get("dose")), _norm(q.get("measure")) or _norm(p.outcome.metric))


def signature(card: HypothesisCard, targets: Optional[Callable[[HypothesisCard], Iterable[str]]] = None,
              aliases: Optional[dict] = None) -> Signature:
    names = Names(aliases)
    triple_ = lambda c: triple(c, card, names)
    keyed = lambda c: (triple_(c), direction(c))
    out = card.outcome_claim
    if card.hypothesis_type == "mechanistic":
        explained = [c for c in card.claims if c.role == "premise"]
        explaining = [c for c in card.claims if c.role in ("outcome", "mechanism")]
    else:
        explained = [out] if out else []
        explaining = [c for c in card.claims if c.role in ("mechanism", "premise")]
    effect = frozenset(keyed(c) for c in explained if triple_(c)) or None
    own = intervention_key(card, names)
    nodes = set()
    for c in card.claims:
        if same_intervention(c, card):
            if c.object.hallmark:
                nodes.add(("hallmark", c.object.hallmark))
            if c.relation in MOLECULAR:
                nodes.add(("node", entity_key(c.object, names)))
    tri = {}
    for c in card.claims:
        t = triple_(c)
        if t is not None:
            tri.setdefault(t, (c.id, direction(c)))
    return Signature(id=card.id, intervention=own, species=species_key(card.pico.population.label)
                     or species_key(card.pico.population.taxon or ""), effect=effect,
                     explanation=frozenset(keyed(c) for c in explaining if triple_(c)),
                     context=_context(card, out), triples=tri,
                     targets=frozenset(targets(card)) if targets else frozenset(), nodes=frozenset(nodes),
                     merged={k: frozenset(v) for k, v in names.merged.items()})


@dataclass
class Relation:
    a: str
    b: str
    types: list[str]
    details: dict = field(default_factory=dict)

    @property
    def approximate(self) -> bool:
        return bool(self.details.get("approximate"))

    def as_dict(self) -> dict:
        return {"a": self.a, "b": self.b, "types": self.types, "details": self.details}


def _same_core(x: Signature, y: Signature) -> bool:
    return x.intervention == y.intervention and x.species == y.species and x.effect is not None and y.effect is not None


def _strip(effect: frozenset) -> frozenset:
    return frozenset(t for t, _ in effect)


def _analog(a: frozenset, b: frozenset) -> str:
    """analog: a shared mechanism target and a shared ATC level-4 class; analog_weak: a shared target and one side
    without ATC, or a shared narrow ChEBI class when at least one side has no mechanism target (the class is then
    the only information); "" otherwise. ATC alone never makes an analog (some level-4 groups name an indication,
    D11AH), nor does a class when both sides have targets (sirolimus and tacrolimus share macrolide lactam)."""
    has_target = lambda k: any(x.startswith("target:") for x in k)
    if not any(k.startswith("target:") for k in a & b):
        if (not has_target(a) or not has_target(b)) and any(k.startswith("class:") for k in a & b):
            return "analog_weak"
        return ""
    atc_a, atc_b = {k for k in a if k.startswith("atc4:")}, {k for k in b if k.startswith("atc4:")}
    if not atc_a or not atc_b:
        return "analog_weak"
    return "analog" if atc_a & atc_b else ""


def relate(x: Signature, y: Signature) -> Optional[Relation]:
    types, details = [], {}
    # claim-level contradictions: the same triple, opposite direction
    clash = [(x.triples[t][0], y.triples[t][0]) for t in set(x.triples) & set(y.triples)
             if x.triples[t][1] != y.triples[t][1]]
    if clash:
        types.append("contradiction")
        details["contradicting_claims"] = sorted(clash)
    if _same_core(x, y) and _strip(x.effect) == _strip(y.effect) and x.effect == y.effect:   # same effect, same direction
        if x.explanation and y.explanation and x.explanation != y.explanation:
            types.append("competitor")
        if x.context != y.context or bool(x.explanation) != bool(y.explanation):
            types.append("variant")
            details["context_differs"] = [k for k, a, b in zip(
                ("sex", "age_at_start", "strain", "regimen", "route", "comparator", "dose", "measure"), x.context, y.context)
                if a != b] + (["mechanism stated in one only"] if bool(x.explanation) != bool(y.explanation) else [])
        if not types:
            types.append("duplicate")
    if x.intervention != y.intervention:
        kind = _analog(x.targets, y.targets)
        if kind:
            types.append(kind)
            shared = sorted(x.targets & y.targets)
            details["shared_targets"] = [k.split(":", 1)[1] for k in shared if k.startswith("target:")]
            atc = [k.split(":", 1)[1] for k in shared if k.startswith("atc4:")]
            details.update({"shared_atc4": atc} if atc else {})
            cls = sorted((k.split(":", 1)[1].split("|") for k in shared if k.startswith("class:")), key=lambda c: int(c[2]))
            if cls:                                       # the most specific common class and its size
                details["shared_class"] = f"{cls[0][0]} {cls[0][1]} ({cls[0][2]})"
            if not details["shared_targets"]:
                del details["shared_targets"]
        nodes = x.nodes & y.nodes
        if nodes:
            types.append("mechanism_neighbour")
            details["shared_nodes"] = sorted(n[1] if n[0] == "hallmark" else "+".join(sorted(n[1])) for n in nodes)
    if not types:
        return None
    approx = sorted({tuple(sorted(x.merged[k] | y.merged[k])) for k in set(x.merged) & set(y.merged)
                     if x.merged[k] != y.merged[k]})
    if approx:
        details["approximate"] = [list(names) for names in approx]      # names merged by embedding similarity
        # embeddings do not separate opposite claims: such a pair is flagged, never collapsed (spec 8b)
        types = ["duplicate_approx" if t == "duplicate" else t for t in types]
    return Relation(x.id, y.id, [t for t in TYPES if t in types], details)


def relations(cards: list[HypothesisCard], targets: Optional[Callable] = None, embedder=None,
              threshold: float = ALIAS_THRESHOLD) -> list[Relation]:
    """Typed relations among the cards, through buckets: same intervention, same claim triple, same target or
    class, same node. With an embedder, near-synonymous names of unresolved entities are merged first."""
    aliases = name_aliases(cards, embedder, threshold) if embedder is not None else {}
    sigs = {c.id: signature(c, targets, aliases) for c in cards}
    buckets = defaultdict(set)
    for s in sigs.values():
        buckets[("i", s.intervention)].add(s.id)
        for t in s.triples:
            buckets[("t", t)].add(s.id)
        for t in s.targets:
            if t.startswith(("target:", "class:")):       # a shared target, or a class (analog_weak), can link
                buckets[("g", t)].add(s.id)
        for n in s.nodes:
            buckets[("n", n)].add(s.id)
    pairs = {tuple(sorted(p)) for ids in buckets.values() if len(ids) > 1 for p in combinations(ids, 2)}
    out = []
    for a, b in sorted(pairs):
        r = relate(sigs[a], sigs[b])
        if r is not None:
            out.append(r)
    return out


def analog_keys(card: HypothesisCard) -> list[str]:
    """ChEMBL mechanism targets, ATC level-4 classes and narrow ChEBI classes of the card's compound
    interventions (union for a combination)."""
    from hyparena.tools import chebi
    out = set()
    for i in card.pico.intervention:
        c = cp.lookup(i.label) if i.type == "compound" else None
        if c is None:
            continue
        out |= {f"target:{t}" for t in c.targets or []}
        out |= {f"atc4:{code[:5]}" for code in c.atc or [] if len(code) >= 5}
        out |= {f"class:{cid}|{label}|{size}" for cid, label, size in chebi.classes(c.chebi)}
    return sorted(out)


# ---- embedding fallback for unresolved names (spec 8b) ----


def unresolved_names(cards: list[HypothesisCard]) -> dict[str, str]:
    """Name key → a label, for every entity without an identifier: interventions, claim subjects and objects
    (organisms excluded: species are compared as species)."""
    out = {}

    def add(label):
        for part in cp.split(label) or [label]:
            k = cp.key(part)
            if k and k not in out:
                out[k] = part
    for card in cards:
        for i in card.pico.intervention:
            if not i.id:
                add(i.label)
        for c in card.claims:
            if not c.subject.id:
                add(c.subject.label)
            if not c.object.id and c.relation not in ORGANISM:
                add(c.object.label)
    return out


def _numbers(text: str) -> tuple:
    return tuple(sorted(re.findall(r"\d+", text)))


def name_aliases(cards: list[HypothesisCard], embedder, threshold: float = ALIAS_THRESHOLD) -> dict[str, str]:
    """Name key → canonical key for groups of near-synonymous names: cosine >= threshold of the embeddings and
    the same numbers in both names (omega-3 / omega-6, mTORC1 / mTORC2, GLP-1 / GIP stay apart). Calibrated on 18
    synonym and 18 non-synonym pairs of ageing entities (2026-10-21): with SapBERT, 0.80 and the number rule
    merged 10 synonym pairs and no other pair."""
    import numpy as np
    names = unresolved_names(cards)
    keys = sorted(names)
    if len(keys) < 2:
        return {}
    vec = embedder.embed([names[k] for k in keys])
    sim = vec @ vec.T
    parent = list(range(len(keys)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, j in zip(*np.where(np.triu(sim, 1) >= threshold)):
        if _numbers(names[keys[i]]) == _numbers(names[keys[j]]):
            parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i, k in enumerate(keys):
        groups[find(i)].append(k)
    return {k: f"~{min(g)}" for g in groups.values() if len(g) > 1 for k in g}


_EMBEDDER = None


def default_embedder():
    """SapBERT when its packages are installed and HYPARENA_EMBEDDER is not "none"; else None (no fallback)."""
    global _EMBEDDER
    import os
    if os.environ.get("HYPARENA_EMBEDDER", "sapbert").lower() == "none":
        return None
    if _EMBEDDER is None:
        try:
            from hyparena.tools.embed import SapBertEmbedder
            _EMBEDDER = SapBertEmbedder()
        except Exception:                                  # packages missing or the model cannot be fetched
            return None
    return _EMBEDDER


def duplicates(rels: list[Relation], order: list[str]) -> dict[str, str]:
    """Card id → the card it duplicates (the earliest in `order` of its duplicate group). Approximate duplicates
    (resting on merged names) are not removed."""
    rank = {h: i for i, h in enumerate(order)}
    parent = {h: h for h in order}

    def find(h):
        while parent[h] != h:
            parent[h] = parent[parent[h]]
            h = parent[h]
        return h
    for r in rels:
        if "duplicate" in r.types and not r.approximate and r.a in parent and r.b in parent:
            ra, rb = find(r.a), find(r.b)
            if ra != rb:
                keep, drop = (ra, rb) if rank[ra] < rank[rb] else (rb, ra)
                parent[drop] = keep
    return {h: find(h) for h in order if find(h) != h}


def competitors(rels: list[Relation]) -> dict[str, list[str]]:
    out = defaultdict(list)
    for r in rels:
        if "competitor" in r.types:
            out[r.a].append(r.b)
            out[r.b].append(r.a)
    return {h: sorted(v) for h, v in out.items()}


def variant_groups(rels: list[Relation]) -> list[list[str]]:
    """Connected groups of variants (same core, other context)."""
    adj = defaultdict(set)
    for r in rels:
        if "variant" in r.types:
            adj[r.a].add(r.b)
            adj[r.b].add(r.a)
    seen, groups = set(), []
    for h in sorted(adj):
        if h in seen:
            continue
        stack, group = [h], set()
        while stack:
            x = stack.pop()
            if x not in group:
                group.add(x)
                stack.extend(adj[x] - group)
        seen |= group
        groups.append(sorted(group))
    return groups
