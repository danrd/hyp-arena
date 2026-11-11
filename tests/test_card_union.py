from hyparena.card.models import HypothesisCard
from hyparena.card.normalizer import normalize_union, union_cards

TEXT = "Squats improve SPPB. They raise muscle mass and leg strength, thereby alleviating pre-sarcopenia. RCT, usual care, 80."


def _card(claims, edges=(), exp=None):
    return HypothesisCard.model_validate({
        "id": "H-1", "hypothesis_type": "interventional", "claim_plain": "x",
        "pico": {"population": {"label": "older adults"}, "intervention": [{"type": "other", "label": "squat exercise"}]},
        "claims": claims, "edges": [{"from": a, "to": b, "type": "requires"} for a, b in edges],
        "decisive_experiment": exp or {}})


C_OUT = {"id": "c1", "subject": {"label": "squat exercise"}, "relation": "improves_healthspan_in", "object": {"label": "human"},
         "qualifiers": {"measure": "SPPB"}, "role": "outcome", "link": "outcome", "source_span": "Squats improve SPPB"}
C_MASS = {"id": "c2", "subject": {"label": "squat exercise"}, "relation": "promotes", "object": {"label": "muscle mass"},
          "role": "premise", "link": "effect", "source_span": "raise muscle mass"}
C_PRE = {"id": "c3", "subject": {"label": "squat exercise"}, "relation": "suppresses", "object": {"label": "pre-sarcopenia"},
         "role": "outcome", "link": "outcome", "source_span": "alleviating pre-sarcopenia"}


def test_union_adds_the_claims_and_edges_only_the_second_parse_wrote_and_keeps_one_outcome():
    a = _card([C_OUT], exp={"design": "unknown", "n_planned": None})
    b = _card([{**C_OUT, "id": "c1", "subject": {"label": "Squat exercise "}}, C_MASS, C_PRE], edges=[("c3", "c2")],
              exp={"design": "rct", "n_planned": 80})
    u, s = union_cards(a, b, TEXT)
    assert [c.id for c in u.claims] == ["c1", "c2", "c3"]                 # c1 matched despite case and spaces
    assert [c.role for c in u.claims] == ["outcome", "premise", "premise"]  # the second parse's outcome becomes a premise
    assert [(e.from_, e.to) for e in u.edges] == [("c3", "c2")]
    assert u.decisive_experiment.design == "rct" and u.decisive_experiment.n_planned == 80
    assert s["shared"] == 1 and s["jaccard"] == round(1 / 3, 3) and s["added_from_second"] == ["c2", "c3"]


def test_a_conflict_keeps_the_first_parse_and_is_reported():
    a = _card([C_OUT], exp={"design": "rct"})
    b = _card([C_OUT], exp={"design": "pilot"})
    u, s = union_cards(a, b, TEXT)
    assert u.decisive_experiment.design == "rct" and s["conflicts"] == ["decisive_experiment.design: 'rct' / 'pilot'"]
    assert s["jaccard"] == 1.0


def test_normalize_union_runs_the_parses_and_survives_a_failed_one(monkeypatch):
    from hyparena.card import normalizer
    outs = iter([(None, ["no valid JSON"]), (_card([C_OUT]), [])])
    monkeypatch.setattr(normalizer, "normalize", lambda *a, **k: next(outs))
    card, problems, stab = normalize_union(None, "google", TEXT, "H-1", runs=2)
    assert card is not None and stab == {"parses": 2, "valid": 1}


def test_the_measure_separates_claims_only_where_the_object_is_the_organism():
    bio = {"id": "c1", "subject": {"label": "squat exercise"}, "relation": "changes_biomarker", "object": {"label": "body composition"},
           "qualifiers": {"measure": "InBody"}, "role": "outcome", "link": "outcome", "source_span": "Squats improve SPPB"}
    strength = {**C_OUT, "id": "c2", "qualifiers": {"measure": "leg strength"}, "role": "premise", "link": "effect"}
    a = _card([bio, C_OUT | {"id": "c3", "role": "premise"}])
    b = _card([{**bio, "qualifiers": {"measure": "body composition"}}, strength])
    u, s = union_cards(a, b, TEXT)
    assert [c.id for c in u.claims] == ["c1", "c3", "c4"] and s["added_from_second"] == ["c4"]   # no id collision
    assert s["shared"] == 1                       # body composition matched whatever its measure; strength is not SPPB
