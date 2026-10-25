import pytest
pytest.importorskip("hypothesis")

from hypothesis import strategies as st, given, settings
from hyparena.card.models import (
    HypothesisCard, Claim, Pico, Population, Outcome, Entity,
    DeclaredAlternative, Intervention, Edge
)
from hyparena.card.rules import validate_card, mark_inherited
import string

SPECIES_VOCAB = ["mouse", "human", "C. elegans", "rat", "unknown"]
STRAIN_VOCAB = ["C57BL/6", "UM-HET3", "N2", "unknown"]
SEX_VOCAB = ["male", "female", "both", "unknown"]
ENDPOINT_VOCAB = ["lifespan", "healthspan", "biomarker", "disease", "mechanism", "unknown"]
RELATION_VOCAB = ['extends_lifespan_in', 'shortens_lifespan_in', 'no_lifespan_effect_in', 'slows_aging_in', 'improves_healthspan_in', 'changes_biomarker', 'predicts', 'inhibits', 'activates', 'increases_expression', 'decreases_expression', 'promotes', 'suppresses', 'part_of', 'associated_with', 'affects_hallmark', 'translates_to', 'other']

@st.composite
def valid_card_strategy(draw):
    species = draw(st.sampled_from(SPECIES_VOCAB))
    strain = draw(st.sampled_from(STRAIN_VOCAB))
    sex = draw(st.sampled_from(SEX_VOCAB))
    endpoint = draw(st.sampled_from(ENDPOINT_VOCAB))

    num_claims = draw(st.integers(min_value=1, max_value=5))
    spans = draw(st.lists(st.text(alphabet=string.ascii_lowercase + " ", min_size=5, max_size=20), min_size=num_claims, max_size=num_claims))
    filler = draw(st.lists(st.text(alphabet=string.ascii_lowercase + " ", min_size=1, max_size=10), min_size=num_claims+1, max_size=num_claims+1))

    raw_text = filler[0]
    for i in range(num_claims):
        raw_text += spans[i] + filler[i+1]

    pico_intervention_label = draw(st.text(alphabet=string.ascii_lowercase, min_size=3, max_size=10))
    pico = Pico(
        population=Population(taxon=species, strain=strain, sex=sex, label="population label"),
        intervention=[Intervention(label=pico_intervention_label)],
        outcome=Outcome(endpoint=endpoint, disease="")
    )

    claims = []
    for i in range(num_claims):
        cid = f"c{i+1}"
        role = "outcome" if i == 0 else draw(st.sampled_from(["mechanism", "premise"]))
        rel = draw(st.sampled_from(RELATION_VOCAB))

        subj_label = draw(st.text(alphabet=string.ascii_lowercase, min_size=3, max_size=10))
        obj_label = draw(st.text(alphabet=string.ascii_lowercase, min_size=3, max_size=10))

        refs = []
        if i > 0:
            num_refs = draw(st.integers(min_value=0, max_value=i))
            if num_refs > 0:
                refs = draw(st.lists(st.sampled_from([f"c{j+1}" for j in range(i)]), min_size=num_refs, max_size=num_refs, unique=True))

        # we start with no inherited_from_pico to avoid validation errors before mark_inherited
        c = Claim(
            id=cid,
            subject=Entity(label=subj_label),
            relation=rel,
            object=Entity(label=obj_label),
            role=role,
            source_span=spans[i],
            qualifiers={"species": "", "strain": ""}, note="x" if rel == "other" else ""
        )
        claims.append((c, refs))

    num_competitors = draw(st.integers(min_value=0, max_value=2))
    competitors = []
    for i in range(num_competitors):
        comp_span = draw(st.text(alphabet=string.ascii_lowercase + " ", min_size=5, max_size=20))
        raw_text += " " + comp_span
        competitors.append(DeclaredAlternative(id=f"alt{i+1}", subject=Entity(label="a"), relation="other", note="x", object=Entity(label="b"), role="alternative", explanation="x", source_span=comp_span, stated_as=draw(st.sampled_from(["listed"]))))

    card = HypothesisCard(
        id=draw(st.text(alphabet=string.ascii_lowercase, min_size=3, max_size=10)),
        raw_id=draw(st.text(alphabet=string.ascii_lowercase, min_size=3, max_size=10)),
        hypothesis_type="mechanistic",
        claim_plain="x",
        pico=pico,
        claims=[c for c, _ in claims],
        edges=[Edge(**{"from": s, "to": c.id, "type": "requires"}) for c, refs in claims for s in refs],
        declared_alternatives=competitors
    )
    return card, raw_text

@settings(max_examples=100, derandomize=True, deadline=None)
@given(valid_card_strategy())
def test_validate_card_returns_no_problems(card_text):
    card, raw_text = card_text
    card = mark_inherited(card)
    problems = validate_card(card, raw_text)
    assert not problems

@settings(max_examples=100, derandomize=True, deadline=None)
@given(valid_card_strategy())
def test_mark_inherited_properties(card_text):
    card, _ = card_text
    card1 = mark_inherited(card)
    card2 = mark_inherited(card1)

    # idempotent
    assert card1 == card2

    # inherited values are subset of {species, strain} and match pico
    for claim in card1.claims:
        for k in claim.inherited_from_pico:
            assert k in ["species", "strain"]
            if k == "species":
                assert claim.qualifiers.get("species") in (card1.pico.population.taxon, card1.pico.population.label)
            elif k == "strain":
                assert claim.qualifiers.get("strain") == card1.pico.population.strain

@settings(max_examples=100, derandomize=True, deadline=None)
@given(valid_card_strategy())
def test_source_span_substring(card_text):
    card, raw_text = card_text
    from hyparena.card.rules import _norm

    card = mark_inherited(card)
    norm_raw = _norm(raw_text)

    for claim in card.claims:
        assert _norm(claim.source_span) in norm_raw

        if len(claim.source_span) > 3:
            # mutate one character
            mutated_span = claim.source_span[:-2] + "@" + claim.source_span[-1:]
            claim.source_span = mutated_span

            problems = validate_card(card, raw_text)
            assert any(claim.id in p and "verbatim" in p for p in problems)

@settings(max_examples=100, derandomize=True, deadline=None)
@given(valid_card_strategy())
def test_claim_reference_graph_acyclic(card_text):
    from hyparena.card.rules import _has_cycle
    card, raw_text = card_text

    edges = {e.from_ for e in card.edges}; graph = {c.id: [e.to for e in card.edges if e.from_ == c.id] for c in card.claims}
    assert not _has_cycle(graph)

    if len(card.claims) > 1:
        # add a back-edge to create a cycle
        from hyparena.card.models import Edge; card.edges.append(Edge(**{"from": card.claims[0].id, "to": card.claims[1].id, "type": "requires"})); card.edges.append(Edge(**{"from": card.claims[1].id, "to": card.claims[0].id, "type": "requires"}))
        problems = validate_card(card, raw_text)
        assert any("cycle" in p for p in problems)

@settings(max_examples=100, derandomize=True, deadline=None)
@given(valid_card_strategy())
def test_round_trip_serialization(card_text):
    card, raw_text = card_text
    card = mark_inherited(card)

    serialized = card.model_dump()
    loaded = HypothesisCard.model_validate(serialized)

    assert card == loaded
    assert validate_card(card, raw_text) == validate_card(loaded, raw_text)

@settings(max_examples=100, derandomize=True, deadline=None)
@given(valid_card_strategy())
def test_metamorphic_population_change(card_text):
    from hyparena.card.rules import _span_names
    card, raw_text = card_text
    card = mark_inherited(card)

    orig_inherited = {c.id: set(c.inherited_from_pico) for c in card.claims}

    # Change species
    new_species = "C. elegans" if card.pico.population.taxon != "C. elegans" else "mouse"
    card2 = HypothesisCard.model_validate(card.model_dump())
    card2.pico.population.taxon = new_species

    card2 = mark_inherited(card2)
    new_inherited = {c.id: set(c.inherited_from_pico) for c in card2.claims}

    for c in card2.claims:
        if orig_inherited[c.id] != new_inherited[c.id]:
            # if inheritance changed, it must be because the new or old species is named in the span
            assert _span_names(c, "species") or "species" not in orig_inherited[c.id]
