"""Method v3 rules on synthetic cases from the paper runs (docs/archive/spec/mechanism-chain-draft.md, method-v3.md section 9.5)."""
import pytest

from hyparena.card import rules_v3 as r3
from hyparena.card.models import ClaimVerification, EvidenceRecord, HypothesisCard


@pytest.fixture(autouse=True)
def no_compound_lookup(monkeypatch):
    """Rules are tested without network lookups; the approval rule has its own test."""
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)


def claim(cid, s, rel, o, link, role="mechanism", hallmark=None, human=True):
    q = {"species": "human"} if human else {}
    return {"id": cid, "subject": {"label": s}, "relation": rel, "object": {"label": o, "hallmark": hallmark}, "qualifiers": q,
            "role": role, "link": link, "source_span": s}


def card(claims, alts=()):
    return HypothesisCard.model_validate({"id": "H-1", "hypothesis_type": "interventional", "claim_plain": "x",
                                          "claims": list(claims), "proposed_alternatives": list(alts)})


def rec(pmid, design, n=None, comparison="between_groups", effect="medium", qm=None, role="finding", trial=""):
    return EvidenceRecord(source="PubMed", record_id=f"PMID:{pmid}", lab_or_cohort=f"PMID:{pmid}", design=design, n_total=n,
                          comparison=comparison, effect_class=effect, quote_role=role, reports_trial=trial,
                          qualifiers_match={"intervention_match": "exact", **(qm or {})})


def test_record_weights_follow_the_levels():
    c = card([claim("c1", "x", "improves_healthspan_in", "human", "outcome", "outcome")]).claims[0]
    big = rec(1, "rct", n=400, effect="large")
    pilot = rec(2, "non_randomised", n=None, comparison="within_group", effect="medium", qm={"population": "no"})
    assert r3.record_weight(big, c, False) == pytest.approx(1.0)
    assert r3.record_weight(pilot, c, False) == pytest.approx((5 / 7) * 0.25 * 0.75 * (2 / 3) * (2 / 3))
    assert r3.record_weight(rec(3, "rct", role="background"), c, False) == 0.0
    assert r3.record_weight(rec(4, "rct", qm={"species": "no", "strain": "no"}), c, False) == 0.0


def test_levothyroxine_restated_trial_triggers_the_gate():
    cs = [claim("c1", "levothyroxine", "decreases_expression", "TSH", "engagement"),
          claim("c2", "subclinical hypothyroidism", "associated_with", "muscle weakness", "pathway", "premise"),
          claim("c3", "levothyroxine", "improves_healthspan_in", "human", "outcome", "outcome")]
    ver = [ClaimVerification(id="c2", evidence=[rec(6, "observational", n=94, effect="medium", qm={"population": "no"})],
                             counterevidence=[rec(9, "observational", n=2290, effect="none")]),
           ClaimVerification(id="c3", evidence=[rec(12, "rct", n=71, effect="small", qm={"population": "no"}),
                                                rec(13, "non_randomised", comparison="within_group", qm={"population": "no"})],
                             counterevidence=[rec(18, "review", n=None, role="background", trial="TRUST trial")])]
    out = r3.evaluate(card(cs), ver)
    assert out.gate == "filtered" and out.V == 0.0 and "find_primary_report" in out.flags
    assert out.links["c2"] == "contested"


def test_invented_chain_stays_low_and_supported_mechanism_is_not_filtered():
    tel = card([claim("c1", "polyphenol X", "activates", "telomerase", "engagement", hallmark="telomere_attrition"),
                claim("c2", "telomerase", "promotes", "stem cell pools", "pathway", hallmark="stem_cell_exhaustion"),
                claim("c3", "stem cell pools", "affects_hallmark", "all hallmarks", "effect"),
                claim("c4", "polyphenol X", "extends_lifespan_in", "human", "outcome", "outcome")],
               alts=[{"id": "p1", "subject": {"label": "ageing"}, "relation": "other", "object": {"label": "multicausal"},
                      "on_positive": "eliminated", "on_negative": "unchanged"}])
    t = r3.evaluate(tel, [])
    assert t.gate == "pass" and t.P == pytest.approx(0.5 ** 4) and t.W == pytest.approx(1 / 3, abs=1e-3) and t.I == pytest.approx(1 / 3, abs=1e-3)
    # NAD-like: an engagement link only weakly supported, a supported hallmark pathway, a weak experiment: kept, flagged
    nad = card([claim("c1", "acipimox", "increases_expression", "muscle NAD+", "engagement"),
                claim("c2", "NAD+", "promotes", "mitochondrial respiration", "pathway", hallmark="mitochondrial_dysfunction"),
                claim("c3", "acipimox", "improves_healthspan_in", "human", "outcome", "outcome")],
               alts=[{"id": "p1", "subject": {"label": "NAD+ decline"}, "relation": "associated_with", "object": {"label": "sarcopenia"},
                      "support_pmids": ["5"], "on_positive": "weakened", "on_negative": "unchanged"}])
    ver = [ClaimVerification(id="c1", evidence=[rec(1, "rct", n=21, effect="medium", qm={"population": "no"})]),
           ClaimVerification(id="c2", evidence=[rec(2, "non_randomised", n=5, comparison="within_group", effect="large",
                                                    qm={"population": "no"})])]
    alt_ver = {"p1": ClaimVerification(id="p1", evidence=[rec(5, "observational", n=120, effect="medium")])}
    n = r3.evaluate(nad, ver, alt_ver)
    assert n.gate == "pass" and n.W == 1.0 and n.V > t.V
    assert "improve_experiment" in n.flags and n.headroom_V > n.V


def test_v2_card_without_links_uses_outcome_mechanism_and_premise():
    c = card([{**claim("c1", "x", "improves_healthspan_in", "human", None, "outcome")}])
    out = r3.evaluate(c, [])
    assert out.links == {"c1": "unverified"} and "build_mechanism" in out.flags and out.gate == "pass"


def test_parallel_outcomes_count_once_by_primary_or_mean():
    cs = [claim("c1", "x", "promotes", "muscle mass", "outcome", "outcome"),
          claim("c2", "x", "promotes", "grip strength", "outcome", "outcome"),
          claim("c3", "x", "promotes", "gait speed", "outcome", "outcome")]
    ver = [ClaimVerification(id="c2", evidence=[rec(1, "rct", n=400, effect="large"), rec(2, "rct", n=400, effect="large")])]
    c = card(cs)
    out = r3.evaluate(c, ver)                                    # no primary outcome stated: mean of 0.5, 1.0, 0.5
    assert out.P == pytest.approx((0.5 + 1.0 + 0.5) / 3, abs=1e-3)
    c.decisive_experiment.primary_outcome = "grip strength"
    assert r3.evaluate(c, ver).P == pytest.approx(1.0)           # the primary outcome decides


def test_no_alternatives_gets_the_lowest_step_and_never_beats_supported_ones():
    base = [claim("c1", "x", "improves_healthspan_in", "human", "outcome", "outcome")]
    none_ = r3.evaluate(card(base), [])
    alt = [{"id": "p1", "subject": {"label": "a"}, "relation": "other", "object": {"label": "b"}, "support_pmids": ["5"],
            "on_positive": "unchanged", "on_negative": "unchanged"}]
    some = r3.evaluate(card(base, alt), [], {"p1": ClaimVerification(id="p1", evidence=[rec(5, "observational", n=120)])})
    assert none_.I == pytest.approx(1 / 3, abs=1e-3) and some.I >= none_.I and none_.V > 0


def test_approved_drug_engagement_link_is_moderate(monkeypatch):
    from types import SimpleNamespace
    import hyparena.card.entities as ent
    monkeypatch.undo()
    monkeypatch.setattr(ent, "subject_compounds", lambda label, card: [SimpleNamespace(max_phase=4, targets=["CHEMBL1"])])
    c = card([claim("c1", "levothyroxine", "decreases_expression", "TSH", "engagement"),
              claim("c2", "levothyroxine", "improves_healthspan_in", "human", "outcome", "outcome")])
    out = r3.evaluate(c, [])
    assert out.links["c1"] == "moderate" and "c1_established_by_approval" in out.flags


def test_intervention_category_is_adjacent_and_class_keeps_full_weight():
    # specs/intervention-class-2026-11-11.yaml: exact and narrow class 1, same broad category only 1/2 (v3.6 context)
    from hyparena.card import rules_v32 as r32
    c = card([claim("c1", "multi-component nutritional formula", "improves_healthspan_in", "human", "outcome", "outcome")]).claims[0]
    w = lambda im: r32.record_weight_v36(rec(1, "rct", n=300, effect="large", qm={"intervention_match": im}), c, False)
    assert r3.context_level(rec(1, "rct", qm={"intervention_match": "category"})) == "adjacent"
    assert w("exact") == pytest.approx(1.0) and w("class") == pytest.approx(1.0) and w("category") == pytest.approx(0.5)
