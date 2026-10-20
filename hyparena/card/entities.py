"""Identifiers for the compounds of a card (card spec 4: "id optional at normalization; resolved later").

Only the interventions the normalizer typed as compounds are looked up (hyparena/tools/compounds.py). A claim's
subject gets identifiers only when every part of it is one of those compounds, by name or synonym: looking up
any subject would turn "SASP" into sulfasalazine. Identifiers are written into the card (`Intervention.id`,
`Entity.id`, a combination as "CHEBI:a+CHEBI:b"); compounds that do not resolve are reported and keep matching
by name. Statuses do not change: the text search works with or without an identifier."""
from __future__ import annotations

from typing import Optional

from hyparena.card.models import HypothesisCard
from hyparena.tools import compounds as cp


def intervention_compounds(card: HypothesisCard) -> dict[str, Optional[cp.Compound]]:
    """Intervention label → its compound (None: not resolved), for interventions typed as compounds."""
    return {i.label: cp.lookup(i.label) for i in card.pico.intervention if i.type == "compound"}


def _by_name(card: HypothesisCard) -> dict[str, cp.Compound]:
    out = {}
    for label, c in intervention_compounds(card).items():
        if c is not None:
            for name in [label, c.name, *c.synonyms]:
                out.setdefault(cp.key(name), c)
    return out


def subject_compounds(label: str, card: HypothesisCard) -> Optional[list[cp.Compound]]:
    """The compounds a claim subject names, when every part is one of the card's compounds."""
    names = _by_name(card)
    parts = cp.split(label)
    found = [names.get(cp.key(p)) for p in parts]
    return found if parts and all(found) else None


def resolve_card(card: HypothesisCard) -> list[str]:
    """Write identifiers into the card; returns the compound interventions that did not resolve."""
    unresolved = []
    for i in card.pico.intervention:
        if i.type != "compound":
            continue
        c = cp.lookup(i.label)
        if c is None:
            unresolved.append(i.label)
        elif not i.id:
            i.id = c.id
    for c in [*card.claims, *card.declared_alternatives]:
        comps = subject_compounds(c.subject.label, card)
        if comps and not c.subject.id:
            c.subject.id = "+".join(sorted({x.id for x in comps}))
    return unresolved


def max_phase(card: HypothesisCard) -> Optional[int]:
    """Clinical phase of the intervention (a combination is as advanced as its least advanced component):
    ChEMBL's max phase; a compound in ChEMBL without a phase counts as preclinical (0); None when an
    intervention is not a resolved compound or not in ChEMBL."""
    comps = intervention_compounds(card)
    if not comps or len(comps) != len(card.pico.intervention) or any(c is None or not c.chembl for c in comps.values()):
        return None
    return min(c.max_phase if c.max_phase is not None else 0 for c in comps.values())
