"""docs/method-v3-manual.md section 12 states the constants of the rules; they must equal the code."""
import re
from pathlib import Path

import yaml

from hyparena.card import rules_v3 as r3
from hyparena.card import v3_levels as lv
from hyparena.card.effect_class import from_phrase
from hyparena.card import aspid_v3, rules_v32 as r32

MANUAL = Path(__file__).resolve().parents[1] / "docs" / "method-v3-manual.md"
HISTORY = Path(__file__).resolve().parents[1] / "docs" / "archive" / "method-history.md"   # earlier versions


def _with_history() -> str:
    return MANUAL.read_text() + "\n" + HISTORY.read_text()


def _constants() -> dict:
    text = MANUAL.read_text()
    block = re.search(r"## 14\. Constants.*?```yaml\n(.*?)```", text, re.S).group(1)
    return yaml.safe_load(block)


def test_manual_constants_equal_the_code():
    c = _constants()
    assert c["link_thresholds"] == {"moderate": r3.MODERATE, "strong": r3.STRONG, "strong_min_independent": 2}
    assert c["informativeness_cap"] == r3.I_CAP
    assert c["effect_unclear_weight"] == lv.weight("effect", "unclear")
    assert [lv.precision_band(n) for n in (29, 30, 99, 100, 299, 300)] == \
        ["lt30", "30_99", "30_99", "100_299", "100_299", "ge300"] and c["precision_bands"] == [30, 100, 300]
    assert {k: list(v) for k, v in c["scales"].items()} == {k: list(v) for k, v in lv.SCALES.items()}


def test_manual_rule_a_thresholds_equal_the_code():
    a = _constants()["effect_class_rule_a"]
    assert from_phrase(f"OR {a['ratio']['large']}") == "large" and from_phrase(f"OR {a['ratio']['medium']}") == "medium"
    assert from_phrase("OR 1.2") == "small"
    sd = a["standardised_difference"]
    assert from_phrase(f"d = {sd['large']}") == "large" and from_phrase(f"d = {sd['medium']}") == "medium"
    pc = a["percent"]
    assert from_phrase(f"{pc['large'] + 1}% increase") == "large" and from_phrase(f"{pc['large']}% increase") == "medium"
    assert from_phrase(f"{pc['medium']}% increase") == "medium" and from_phrase(f"{pc['medium'] - 1}% increase") == "small"


def test_manual_v32_constants_and_profiles_equal_the_code():
    c = _constants()
    v = c["v32"]
    assert abs(v["c_anchor"] - r32.C_ANCHOR) < 1e-5 and v["fold_rest"] == r32.FOLD_REST and v["p_floor_aspid"] == aspid_v3.P_FLOOR
    assert r32.precision(None) == v["precision"]["floor"] and r32.precision(v["precision"]["full_at_n"]) == 1.0
    assert r32.precision(v["precision"]["full_at_n"] - 1) < 1.0
    assert {k: p.tiers for k, (p, _) in aspid_v3.load().items()} == c["profiles"]
    from hyparena.card import novelty_v34 as nv
    assert c["v34"] == {"preclinical_precision": r32.PRECLINICAL_PRECISION, "novelty_levels": list(nv.LEVELS)}
    from hyparena.card import review_kind as rk
    assert c["meta_certainty"] == {**rk.CERTAINTY_WEIGHT, "not_reported": rk.NOT_REPORTED}
    from hyparena.card import v3_extra as vx                   # feasibility, written out after an outside report (2026-11-11)
    f = c["feasibility"]
    assert f["system"] == vx.SYSTEM_COST
    assert {k: round(v, 6) for k, v in vx.DURATION_COST.items()} == f["duration"]
    for bound, score in f["n_bands"]:
        assert abs(vx._n_score(bound - 1) - score) < 1e-6 and vx._n_score(bound) < score
    assert vx._n_score(1000) == 0.0


def test_manual_worked_example_is_what_the_code_gives(monkeypatch):
    monkeypatch.setattr(r32, "EMPTY_SLOTS", "count")                     # history: v3.3-v3.6 averaged empty slots in
    from hyparena.card import rules_v3 as r3
    from hyparena.card.models import ClaimVerification
    from tests.test_analyze import _case
    from tests.test_rules_v3 import rec
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)
    c, cvs, alts = _case()
    ev = lambda extra=(): r32.evaluate(c, cvs + list(extra), alts, fold=True, neutral_unverified=True)
    e = ev()
    text = _with_history()
    row = f"| v3.3 | S {e.links['c1'][0]:.3f} (F {e.links['c1'][3]:.3f}) | no record, not in P | S {e.links['c3'][0]:.3f} (F {e.links['c3'][3]:.2f}) | " \
          f"{e.P:.3f} [{e.P_lo:.3f}; {e.P_hi:.3f}] | {e.support_share:.3f} | {e.I:.3f} | {e.scope} | {e.V:.3f} |"
    assert row in text, row
    e2 = ev([ClaimVerification(id="c2", evidence=[rec(5, "animal", n=40, effect="large")])])
    assert f"| S {e2.links['c2'][0]:.3f} | | {e2.P:.3f} | {e2.support_share:.3f} | | {e2.scope} | {e2.V:.3f} |" in text
    e3 = ev([ClaimVerification(id="c2", counterevidence=[rec(6, "animal", n=40, effect="large")])])
    assert f"| S {e3.links['c2'][0]:.3f} | | {e3.P:.3f} | {e3.support_share:.3f} |" in text
    from hyparena.card import aspid_v3
    pts = {k: ({"P": x.P, "scope": x.scope, "I": x.I, "headroom_I": x.I, "gate": "pass"}, {"support_share": x.support_share, "chain_state": x.chain_state}) for k, x in (("a", e), ("b", e2))}
    for prof in ("evidence", "funding"):
        r = aspid_v3.rank(pts, prof, K=10000)
        assert r.expected["b"] > r.expected["a"]                     # support found: the score rises under every profile


def test_manual_worked_example_v34(monkeypatch):
    monkeypatch.setattr(r32, "EMPTY_SLOTS", "count")                     # history: v3.3-v3.6 averaged empty slots in
    from hyparena.card import novelty_v34 as nv
    from hyparena.card.models import ClaimVerification
    from tests.test_analyze import _case
    from tests.test_rules_v3 import rec
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)
    c, cvs, alts = _case()
    ev = lambda extra=(): r32.evaluate(c, cvs + list(extra), alts, v34=True)
    e = ev()
    text = _with_history()
    row = f"| v3.4 | S {e.links['c1'][0]:.3f} (F {e.links['c1'][3]:.3f}) | no record, R 1 | S {e.links['c3'][0]:.3f} (F {e.links['c3'][3]:.2f}) | " \
          f"{e.P:.3f} | {e.support_share:.3f} | {e.I:.3f} | {e.scope} | {e.V:.3f} |"
    assert row in text, row
    e2 = ev([ClaimVerification(id="c2", evidence=[rec(5, "animal", n=40, effect="large")])])
    assert f"| v3.4, with one mouse study of 40 for c2 | | S {e2.links['c2'][0]:.3f} | | {e2.P:.3f} | {e2.support_share:.3f} | | {e2.scope} | {e2.V:.3f} |" in text
    e3 = ev([ClaimVerification(id="c2", counterevidence=[rec(6, "animal", n=40, effect="large")])])
    assert f"| v3.4, with one mouse study of 40 against c2 | | S {e3.links['c2'][0]:.3f} | | {e3.P:.3f} | {e3.support_share:.3f} |" in text
    assert nv.novelty(c, cvs, e) == "new_context" and "Novelty: new context" in text
    from hyparena.card import aspid_v3
    pts = {k: ({"P": x.P, "scope": x.scope, "I": x.I, "headroom_I": x.I, "gate": "pass"},
               {"support_share": x.support_share, "chain_state": x.chain_state, "N": "new_context"}) for k, x in (("a", e), ("b", e2))}
    for prof, (p, ids) in aspid_v3.load().items():
        if "support_share" not in ids and "chain_state" not in ids:
            continue
        r = aspid_v3.rank(pts, prof, K=10000)
        assert r.expected["b"] > r.expected["a"]                     # support found: the score rises


def test_manual_worked_example_v36(monkeypatch):
    monkeypatch.setattr(r32, "EMPTY_SLOTS", "count")                     # history: v3.3-v3.6 averaged empty slots in
    from hyparena.card.models import ClaimVerification
    from tests.test_analyze import _case
    from tests.test_rules_v3 import rec
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)
    c, cvs, alts = _case()
    ev = lambda extra=(): r32.evaluate(c, cvs + list(extra), alts, v36=True)
    e = ev()
    text = _with_history()
    row = f"| v3.6 | S {e.links['c1'][0]:.3f} (F {e.links['c1'][3]:.3f}) | no record | S {e.links['c3'][0]:.3f} (F {e.links['c3'][3]:.3f}) | " \
          f"evidence balance {e.chain_state:.3f} | | {e.I:.3f} | {e.scope} | |"
    assert row in text, row
    e2 = ev([ClaimVerification(id="c2", evidence=[rec(5, "animal", n=40, effect="large")])])
    assert f"| v3.6, with one mouse study of 40 for c2 | | S {e2.links['c2'][0]:.3f} | | evidence balance {e2.chain_state:.3f} |" in text
    e3 = ev([ClaimVerification(id="c2", counterevidence=[rec(6, "animal", n=40, effect="large")])])
    assert f"| v3.6, with one mouse study of 40 against c2 | | S {e3.links['c2'][0]:.3f} | | evidence balance {e3.chain_state:.3f} |" in text


def test_manual_v36_constants_equal_the_code():
    import yaml
    block = MANUAL.read_text().split("## 14. Constants (checked against the code)")[1].split("```yaml")[1].split("```")[0]
    v = yaml.safe_load(block)["v36"]
    assert abs(v["loglr_lambda"] - r32.LOGLR_LAMBDA) < 1e-5 and abs(v["effect_full_from"] - r32.EFFECT_FULL_FROM) < 1e-9
    d = dict(v["design_grade3"])
    assert d.pop("other") == 0.25 and d == r32.DESIGN_GRADE3
    assert yaml.safe_load(block)["v37"]["empty_slots"] == r32.EMPTY_SLOTS


def test_manual_names_table_matches_code():
    """Section 10a lists every display name the code uses (user note 2026-11-09: outside reports must use the same names)."""
    from hyparena import report_html as rh
    from hyparena import report_v2 as r2
    text = (Path(__file__).resolve().parents[1] / "docs" / "method-v3-manual.md").read_text(encoding="utf-8")
    sec = text[text.index("## 10a."):text.index("## 11.")]
    pairs = [(k, v[0]) for d in (rh.IND_NAMES, rh.LINK_NAMES, rh.DESIGN_NAMES, rh.DISC, r2.FLAG_NAMES) for k, v in d.items()]
    pairs += [(k or "unknown", v[0]) for k, v in rh.NOVELTY_NAMES.items()] + list(r2.PROFILE_LABEL.items())
    for code, ru in pairs:
        assert f"| `{code}` | {ru} |" in sec, (code, ru)


def test_manual_worked_example_v37(monkeypatch):
    """v3.7: a slot with no record is left out of the balance."""
    from hyparena.card.models import ClaimVerification
    from tests.test_analyze import _case
    from tests.test_rules_v3 import rec
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)
    monkeypatch.setattr(r32, "EMPTY_SLOTS", "skip")
    c, cvs, alts = _case()
    e = r32.evaluate(c, cvs, alts, v36=True)
    text = MANUAL.read_text()
    assert f"| v3.7 | S {e.links['c1'][0]:.3f} (F {e.links['c1'][3]:.3f}) | no record, not averaged | S {e.links['c3'][0]:.3f} (F {e.links['c3'][3]:.3f}) | evidence balance {e.chain_state:.3f} |" in text
    e2 = r32.evaluate(c, cvs + [ClaimVerification(id="c2", evidence=[rec(5, "animal", n=40, effect="large")])], alts, v36=True)
    assert f"| v3.7, with one mouse study of 40 for c2 | | S {e2.links['c2'][0]:.3f} | | evidence balance {e2.chain_state:.3f} |" in text
