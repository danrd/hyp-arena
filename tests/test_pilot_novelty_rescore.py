import pytest

from scripts.scoring.pilot_novelty_rescore import cap_novelty


@pytest.mark.parametrize(("level", "relation", "species", "distinct", "strict", "broad"), [
    ("new_link", "same", "different", "no", "translation", "translation"),
    ("new_combination", "same", "same", "no", "new_context", "new_context"),
    ("new_combination", "related", "different", "no", "new_combination", "analog"),
    ("new_mechanism", "same", "same", "yes", "new_mechanism", "new_mechanism"),
    ("new_link", "related", "different", "unknown", "new_link", "new_link"),
    ("new_context", "same", "different", "no", "new_context", "new_context"),
    (None, "same", "different", "no", None, None),
])
def test_predecessor_cap(level, relation, species, distinct, strict, broad):
    comparison = {"relation": relation, "species": species, "distinct_test": distinct}
    assert cap_novelty(level, comparison, broad=False) == strict
    assert cap_novelty(level, comparison, broad=True) == broad
