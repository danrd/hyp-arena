"""Level 4 (specs/evolution/generation-comparison-2026-11-14.yaml): the comparison code on the fake LLM, and the checks of
the outside model's answers."""
import json

import yaml

from hyparena.pipeline import _client
from scripts.argon import generation_tasks as gt
from scripts.evolution import generation_compare as gc

CFG = yaml.safe_load(open(gc.CONFIG))


def _data(tmp_path):
    def hyp(i, parent=None):
        return {"id": i, "parent": parent, "terms": ["Kir2.1 channel", "muscle strength"],
                "text": f"Raising Kir2.1 channel expression hyperpolarises aged muscle ({i}).\n"
                        "A more negative membrane potential restores calcium handling and muscle strength.\n"
                        "Old mice get AAV-Kir2.1 or a control vector; grip strength at 12 weeks."}
    arms = {"A": [hyp(f"A{k}") for k in range(1, 6)], "B": [hyp(f"B{k}") for k in range(1, 6)],
            "C": [hyp(f"C{k}", f"B{k}") for k in range(1, 6)], "D": [hyp(f"D{k}", f"A{k}") for k in range(1, 6)]}
    data = {"topic": "bioelectricity", "as_of": "2026-11-14", "writer_family": "google", "arms": arms}
    (tmp_path / "hypotheses.json").write_text(json.dumps(data))
    return data


def test_pairs_follow_the_spec(tmp_path):
    data = _data(tmp_path)
    by = {}
    for c, a, b, _ in gc.pairs(data["arms"]):
        by.setdefault(c, []).append((a, b))
    assert len(by["B>A"]) == 25 and len(by["C>A"]) == 25
    assert sorted(by["C>B"]) == [(f"C{k}", f"B{k}") for k in range(1, 6)]
    assert sorted(by["D>A"]) == [(f"D{k}", f"A{k}") for k in range(1, 6)]


def test_writer_and_rewriter_never_judge(tmp_path):
    fams = gc.judges(CFG, _data(tmp_path))
    assert "google" not in fams and CFG["rewriter"] not in fams and len(fams) >= 4


def test_both_orders_make_one_outcome():
    data = {"arms": {"B": [{"id": "B1"}], "A": [{"id": "A1"}]}}
    win = {"pair|B>A|B1|A1|openai|ab": {"overall": "1"}, "pair|B>A|B1|A1|openai|ba": {"overall": "2"}}
    split = {"pair|B>A|B1|A1|openai|ab": {"overall": "1"}, "pair|B>A|B1|A1|openai|ba": {"overall": "1"}}
    assert gc.pair_outcomes(data, win, ["openai"])[0]["score"] == 1.0
    assert gc.pair_outcomes(data, split, ["openai"])[0]["score"] == 0.5     # the first-shown text won twice: a tie


def test_meaning_check_and_fallback():
    h = {"text": "Kir2.1 hyperpolarises muscle.\nWhy.\nTest.", "terms": ["Kir2.1 channel", "grip strength"]}
    assert gc.meaning_kept(h, {"claim": "Kir2.1 channel in muscle", "rationale": "x", "experiment": "grip strength test"}) == []
    assert gc.meaning_kept(h, {"claim": "a drug", "rationale": "x", "experiment": "y"})
    f = gc.shortened({"text": "One. Two. Three."})
    assert f["shortened_by_rule"] and f["claim"]


def test_format_judge_score_on_the_fake_llm(tmp_path):
    data = _data(tmp_path)
    client, _ = _client(gc.CONFIG, True, 5000)
    assert gc.do_format(tmp_path, client, CFG)["formatted"] == 20
    out = gc.do_judge(tmp_path, client, CFG)
    fams = gc.judges(CFG, data)
    assert out["failed"] == 0 and out["judgements"] == len(gc.jobs(data, fams))
    res = gc.do_score(tmp_path, CFG)
    assert set(res["rule"]) == {"B>A", "C>B", "D>A"}
    ba = res["comparisons"]["B>A"]
    assert 0 <= ba["win_share"] <= 1 and ba["ci95"][0] <= ba["win_share"] <= ba["ci95"][1]
    assert set(ba["per_family"]) == set(fams) and set(res["rubric"]) == {"A", "B", "C", "D"}
    dry = gc.do_dry(tmp_path, CFG)
    assert dry["usd_total"] > 0 and "google" not in dry["by_family"]


def test_answer_checks():
    assert gt.quote_found("Kir2.1 hyperpolarises muscle.", "T", "We show Kir2.1 hyperpolarises muscle. More.") == "whole"
    joined = "Kir2.1 hyperpolarises aged muscle fibres. Calcium handling was restored in them."
    assert gt.quote_found(joined, "", "Kir2.1 hyperpolarises aged muscle fibres. X Y. Calcium handling was restored in them.") == "joined"
    assert gt.quote_found("Something else entirely here.", "", "Kir2.1 hyperpolarises muscle.") == "no"
    assert gt.title_matches("Kir2.1 and muscle ageing", "Kir2.1 channels in muscle ageing of mice")
    assert not gt.title_matches("Lactation in cows", "Kir2.1 channels in muscle ageing")
    assert gt.card_problems({"intervention": {"label": "x"}, "outcome": "y", "links": [{"role": "step"}],
                             "decisive_experiment": {"system": "mouse", "design": "rct", "endpoint": "grip"}}) == []
    assert "no outcome" in gt.card_problems({"intervention": {"label": "x"}})


def test_tasks_carry_the_manual_only_where_the_method_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(gt, "DIR", tmp_path)
    a, b = gt.build_a("2026-11-14"), gt.build_b("2026-11-14")
    assert "manual" not in a and len(b["manual"]) > 10000
    assert (tmp_path / "task_a.json").exists() and b["answer_format"]["hypotheses"][0]["card"]


def test_participants_are_the_base_plus_at_most_one_block(tmp_path, monkeypatch):
    """Independent blocks: every participant is [base] + its block + COMMON, so each difference from A is one block."""
    monkeypatch.setattr(gt, "DIR", tmp_path)
    tasks = {p: gt.build(p, "2026-11-16") for p in gt.PARTICIPANTS}
    a = tasks["a"]["instructions"]
    assert a == [gt.base()] + gt.COMMON
    for p in ("b", "s"):
        spec, fields = gt.PARTICIPANTS[p]
        assert tasks[p]["instructions"] == [gt.base()] + spec(gt.N) + gt.COMMON
        h = tasks[p]["answer_format"]["hypotheses"][0]
        assert set(h) == set(gt.HYP) | {"id"} | set(fields)
    assert tasks["a"]["answer_format"]["hypotheses"][0].keys() == gt.HYP.keys()
    assert gt.build_a("2026-11-16") == tasks["a"] and gt.build_b_generate("2026-11-16") == tasks["b"]
    steps = " ".join(gt.STEPS_SPEC).lower()
    assert not any(w in steps for w in ("score", "axis", "weight", "profile", "manual", "card"))   # no hint of scoring
    t = gt.build("s", "2026-11-16", topic="senolytics", n=4, write=False)
    assert t["topic"] == "senolytics" and "Write 4 " in t["instructions"][0] and "four hypotheses" in t["instructions"][0]
    body = [" ".join(gt.build(p, "2026-11-16", write=False)["instructions"]) for p in gt.PARTICIPANTS]
    assert all(b.count("must be different ideas") == 1 and b.count("Each hypothesis is about people") == 1 for b in body)          # in the base only, so every participant has it
    assert len({gt.build(p, "2026-11-16", write=False)["cover"] for p in gt.PARTICIPANTS}) == 1


def test_check_block_problems_and_refs():
    good = {"steps": [{"step": "x", "for": [{"pmid": "123", "title": "t"}], "against": []}], "alternatives": [{"text": "y"}],
            "tested_before_T": {"answer": "no", "papers": [{"pmid": "456", "title": "u"}]}, "against_whole": [{"pmid": "789"}]}
    assert gt.check_problems(good) == []
    assert len(gt.check_problems({})) == 3
    where = {w for _, _, w in gt._pmids({"check": good})}
    assert where == {"check_for", "check_tested", "check_against_whole"}
    assert gt.format_problems("s", {"hypotheses": [{"id": "S1", "claim": "c", "rationale": "r", "experiment": "e"}] * gt.N}) == []


def test_bs_joins_card_and_steps_once():
    bs = gt.build("bs", "2026-11-16", write=False)
    ins, h = bs["instructions"], bs["answer_format"]["hypotheses"][0]
    assert ins[0] == gt.base() and ins[-len(gt.COMMON):] == gt.COMMON
    body = " ".join(ins)
    assert body.count("extra requirement") == 1 and body.count("Write the claim") == 1
    assert all(item in ins for item in gt._CARD_ITEMS)                       # BS = B + the check
    assert "card" in h and h["check"]["steps"][0]["link"] == "c1" and "step" not in h["check"]["steps"][0]
    card = {"links": [{"id": "c1"}, {"id": "c2"}]}
    chk = {"steps": [{"link": "c1"}, {"link": "c9"}], "alternatives": [{"text": "x"}], "tested_before_T": {"answer": "partly"}}
    assert gt.check_problems(chk, card) == ["check steps name links not in the card: ['c9']"]


def test_score_passes_text_only_and_summarises_numbers(tmp_path, monkeypatch):
    """The pipeline gets claim + rationale + experiment only; card, check and references are not passed."""
    monkeypatch.setattr(gt, "DIR", tmp_path)
    gt.build("bs", "2026-11-16")
    h = {"id": "BS1", "claim": "C.", "rationale": "R.", "experiment": "E.", "relies_on": [{"pmid": "1", "title": "secret ref"}],
         "card": {"outcome": "secret card"}, "check": {"alternatives": [{"text": "secret alt"}]}}
    (tmp_path / "answer_bs.json").write_text(json.dumps({"hypotheses": [h]}))
    seen = []

    def fake_run(texts, **kw):
        seen.append((texts, kw))
        return {"items": [{"outcome": "ranked", "v3": {"gate": "pass", "P": 0.5, "W": 0.3, "I": 0.4, "V": 0.06, "scope": "organ",
                                                        "links": {"c1": "moderate"}, "flags": ["x"]}}],
                "usage": {"total": {"usd": 0.07}}, "calls": [{"kind": "llm"}, {"kind": "pubmed"}]}
    import hyparena.pipeline
    monkeypatch.setattr(hyparena.pipeline, "run", fake_run)
    r = gt.score("bs", fake=True)
    (texts, kw), = seen
    assert texts == ["C.\nR.\nE."] and "secret" not in texts[0] and kw["as_of"] == "2026-11-16" and kw["fake"]
    assert r == {"hypotheses": {"BS1": {"outcome": "ranked", "gate": "pass", "P": 0.5, "W": 0.3, "I": 0.4, "V": 0.06,
                                        "scope": "organ", "links": 1, "flags": 1, "taxon": None}},
                 "not_human": 1, "llm_calls": 1, "usd": 0.07}
    assert gt.score("bs", fake=True) == r and len(seen) == 1                    # resumable: a done id is not run again
