from hyparena.card import canonical
from hyparena.tools import compounds as cp
from scripts.paraphrase_check import facets, main_index


def test_age_is_written_in_one_form():
    assert [canonical.age(x) for x in ("4 months", "4 months of age", "4 mo", "from 4 mo", "6 weeks old", "1.5 years", "at birth")] == \
        ["4 months", "4 months", "4 months", "4 months", "6 weeks", "1.5 years", "at birth"]


def test_ppm_dose_is_written_with_its_route_and_other_doses_are_left_alone():
    assert canonical.dose("30 ppm food") == canonical.dose("30 ppm in food") == canonical.dose("30 ppm", "diet") == "30 ppm food"
    assert canonical.dose("2000 ppm in drinking water") == "2000 ppm water" and canonical.dose("30 ppm") == "30 ppm"
    assert canonical.dose("5 mg/kg/day") == "5 mg/kg/day"


def test_abbreviations_resolve_to_their_full_name_before_the_lookup(monkeypatch):
    assert cp.resolve_alias("DNP") == "2,4-dinitrophenol" and cp.resolve_alias("β-GPA") == "beta-guanidinopropionic acid"
    assert cp.resolve_alias("aspirin") == "aspirin"
    seen = []
    monkeypatch.setattr(cp, "parent_cid", lambda name: seen.append(name) or None)
    monkeypatch.setattr(cp, "_load", lambda: {})
    monkeypatch.setattr(cp, "_save", lambda: None)
    from tests.conftest import REAL_LOOKUP
    REAL_LOOKUP("DNP")
    assert seen == ["2,4-dinitrophenol"]


def _card(roles):
    return {"claims": [{"role": r, "subject": {"label": "X"}, "relation": "extends_lifespan_in", "object": {"label": "mouse"}, "qualifiers": {}} for r in roles]}


def test_the_main_claim_is_the_outcome_claim_not_the_first_one():
    card = _card(["premise", "premise", "outcome"])
    assert main_index(card) == 2 and facets(card)["relation"] == "extends_lifespan_in" and main_index(_card(["premise"])) == 0
