"""End to end over the worked examples: rules → indicators → aggregation per profile."""
from pathlib import Path

import yaml

from hyparena.card.models import HypothesisCard, Verification
from hyparena.card.rank import rank

FIX = Path(__file__).parent / "fixtures" / "cards"


def items():
    out = []
    for name in ("ex1_rapamycin_healthspan", "ex2_senolytics_function", "ex3_rapamycin_mechanism", "ex5_resveratrol_endpoint"):
        d = yaml.safe_load((FIX / f"{name}.yaml").read_text(encoding="utf-8"))
        out.append((HypothesisCard.model_validate(d["card"]), Verification.model_validate(d["verification"]), None))
    for case in yaml.safe_load((FIX / "ex4_admission.yaml").read_text(encoding="utf-8"))["cases"]:
        ver = Verification.model_validate(case.get("verification") or {"card_id": case["card"]["id"]})
        out.append((HypothesisCard.model_validate(case["card"]), ver, None))
    return out


def test_rank_examples():
    r = rank(items(), K=4000, k_top=1)
    assert set(r.filtered) == {"H-0003", "H-0006"}
    assert r.known_results == ["H-0004a"]
    assert set(r.not_admitted) == {"H-0004", "H-0005"}
    assert set(r.ranked) == {"H-0001", "H-0002"}
    v1, v2 = r.values["H-0001"], r.values["H-0002"]
    assert (v1["effect_level"], v1["robustness"], v1["multi_site_positive"]) == ("mammals", "replicated", "positive")
    assert (v2["effect_level"], v2["robustness"], v2["multi_site_positive"]) == ("mammals", "single", "no")
    assert v1["both_sexes"] == "both" and v1["effect_size"] == 14
    assert v1["path_to_human"] is None and v1["novelty"] == "translation"   # no human-safety input given here
    # rapamycin (replicated in a multi-site program) is ahead under "verified evidence matters most"
    ev = r.by_profile["evidence_first"]
    assert ev.order[0] == "H-0001" and ev.pairwise["H-0001"]["H-0002"] > 0.5


def test_path_to_human_steps():
    from hyparena.card.indicators import path_to_human
    assert path_to_human("mammals", True) == "0"
    assert path_to_human("invertebrates", True) == "1"           # a mouse study first
    assert path_to_human("mammals", False) == "1"                 # a safety package first
    assert path_to_human("none", False) == "2"
    assert path_to_human("mammals", None) is None                 # gene target without a drug


def test_rank_with_human_safety():
    its = [(c, v, {"human_safety": True}) for c, v, _ in items()]
    r = rank(its, K=2000, k_top=1)
    assert r.values["H-0001"]["path_to_human"] == "0" and r.values["H-0002"]["path_to_human"] == "0"
