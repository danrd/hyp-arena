"""docs/method-v3-manual.md section 12 states the constants of the rules; they must equal the code."""
import re
from pathlib import Path

import yaml

from hyparena.card import rules_v3 as r3
from hyparena.card import v3_levels as lv
from hyparena.card.effect_class import from_phrase
from hyparena.card import aspid_v3, rules_v32 as r32

MANUAL = Path(__file__).resolve().parents[1] / "docs" / "method-v3-manual.md"


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


def test_manual_worked_example_is_what_the_code_gives(monkeypatch):
    from hyparena.card import rules_v3 as r3
    from hyparena.card.models import ClaimVerification
    from tests.test_analyze import _case
    from tests.test_rules_v3 import rec
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)
    c, cvs, alts = _case()
    ev = lambda extra=(): r32.evaluate(c, cvs + list(extra), alts, fold=True, neutral_unverified=True)
    e = ev()
    text = MANUAL.read_text()
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
    from hyparena.card import novelty_v34 as nv
    from hyparena.card.models import ClaimVerification
    from tests.test_analyze import _case
    from tests.test_rules_v3 import rec
    monkeypatch.setattr(r3, "established_by_approval", lambda claim, card: False)
    c, cvs, alts = _case()
    ev = lambda extra=(): r32.evaluate(c, cvs + list(extra), alts, v34=True)
    e = ev()
    text = MANUAL.read_text()
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
