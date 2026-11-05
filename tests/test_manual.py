"""docs/method-v3-manual.md section 12 states the constants of the rules; they must equal the code."""
import re
from pathlib import Path

import yaml

from hyparena.card import rules_v3 as r3
from hyparena.card import v3_levels as lv
from hyparena.card.effect_class import from_phrase

MANUAL = Path(__file__).resolve().parents[1] / "docs" / "method-v3-manual.md"


def _constants() -> dict:
    text = MANUAL.read_text()
    block = re.search(r"## 12\. Constants.*?```yaml\n(.*?)```", text, re.S).group(1)
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
