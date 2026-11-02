"""Vocabulary guard of model-written PubMed queries."""
from hyparena.card.search_vocab import filter_query, term_allowed


V = {"words": {"creatine", "older", "adults", "muscle", "mass", "hip", "fracture", "growth", "hormone", "insulin-like", "factor"},
     "phrases": {"creatine monohydrate"}}


def test_terms_outside_the_vocabulary_are_dropped_and_logged():
    q, dropped = filter_query('(creatine[tiab] OR aspirin[tiab]) AND (older adults[tiab]) AND "muscle mass"[tiab]', V, "strict")
    assert "aspirin" not in q and dropped == ["aspirin[tiab]"]
    assert q.startswith("creatine[tiab]") and "muscle mass" in q


def test_multiword_terms_stay_whole_and_plurals_match():
    q, dropped = filter_query("(growth hormone[tiab] OR insulin-like growth factor[tiab]) AND hip fractures[MeSH]", V, "strict")
    assert dropped == [] and "insulin-like growth factor[tiab]" in q and "hip fractures[MeSH]" in q


def test_an_emptied_concept_group_is_removed_and_publication_types_pass():
    q, dropped = filter_query("creatine[tiab] AND (aspirin[tiab] OR ibuprofen[tiab]) AND randomized controlled trial[pt]", V, "strict")
    assert q == "creatine[tiab] AND randomized controlled trial[pt]" and len(dropped) == 2
    assert term_allowed("creatine monohydrate[tiab]", V)


def test_light_guard_keeps_topic_widening_and_drops_steering():
    v = {**V, "card_words": {"creatine", "muscle", "mass"}}
    q, dropped = filter_query('creatine[tiab] AND (dementia[tiab] OR AKG[tiab] OR "no effect"[tiab] OR improved[tiab] OR SPRINT[tiab] '
                              'OR NCT01234567 OR Smith J[au]) AND muscle mass[tiab]', v)
    assert "dementia[tiab]" in q and "AKG[tiab]" in q
    assert sorted(dropped) == sorted(['"no effect"[tiab]', "improved[tiab]", "SPRINT[tiab]", "NCT01234567", "Smith J[au]"])
