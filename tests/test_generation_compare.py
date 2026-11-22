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


def test_single_question_judge_mode():
    """Pilot of 2026-11-16: one question (v2), no rubric; BS is compared with A in every cross pair, both orders."""
    from scripts.evolution import generation_compare as gc
    try:
        gc.set_mode({"judge": {"pair_version": "v2", "rubric": False}})
        data = {"arms": {"A": [{"id": f"A{i}"} for i in range(5)], "BS": [{"id": f"BS{i}"} for i in range(5)]}}
        js = gc.jobs(data, ["openai", "qwen"])
        assert len(js) == 25 * 2 * 2 and all(j[0] == "pair" and j[1] == "BS>A" for j in js)
        assert gc.pair_problems({"overall": "1"}) == [] and gc.pair_problems({"overall": "x"})
        assert "novelty" not in gc.render("judge_pair", "v2", topic="t", first="a", second="b", history_text="").split("Do not judge")[0]
    finally:
        gc.set_mode({})


def test_references_cut_without_rewriting():
    from scripts.evolution import generation_compare as gc
    h = {"claim": "X improves Y (PMID 12345678).", "rationale": "Shown before [3, 4] and by Smith et al., 2019 (Smith et al., 2019); "
         "PMIDs 11111111, 22222222 agree.", "experiment": "A trial (Jones and Brown, 2021) over 12 weeks."}
    f = gc.unreferenced(h)
    text = gc.judged_text(f)
    assert "PMID" not in text and "[3" not in text and "(Smith" not in text and "(Jones" not in text
    assert "X improves Y." in text and "12 weeks" in text and f["references_cut"] == 5 and not f["rewritten"]


def test_guard_lines_in_the_base_and_the_control(tmp_path, monkeypatch):
    """2026-11-17: frame, one excluded kind of intervention and the length, in the base of every participant; the control
    request is the earlier base."""
    monkeypatch.setattr(gt, "DIR", tmp_path)
    for p in gt.PARTICIPANTS:
        b = gt.build(p, "2026-11-17", write=False)["instructions"][0]
        assert gt.GUARD in b and f"at most {gt.MAX_CHARS} characters" in b
    ctrl = gt.build("a", "2026-11-17", guard=False)
    assert gt.GUARD not in ctrl["instructions"][0] and (tmp_path / "task_a_noguard.json").exists()
    assert ctrl["instructions"][0] + " " + gt.GUARD in gt.base()


def test_judge_v3_needs_the_deciding_consideration():
    from scripts.evolution import generation_compare as gc
    gc.set_mode({"judge": {"pair_version": "v3", "rubric": False, "rewrite": False}})
    try:
        assert gc.pair_problems({"overall": "1", "decided_by": "evidence", "reason": "x"}) == []
        assert gc.pair_problems({"overall": "1", "reason": "x"})
        data = {"arms": {"A": [{"id": "A1"}], "BS": [{"id": "BS1"}]}}
        done = {"pair|BS>A|BS1|A1|q|ab": {"overall": "1", "decided_by": "evidence"},
                "pair|BS>A|BS1|A1|q|ba": {"overall": "1", "decided_by": "benefit"}}
        assert gc.decided_by(data, done, ["q"]) == {"BS>A": {"x": {"evidence": 1}, "y": {"benefit": 1}}}
    finally:
        gc.set_mode({})


def test_v3_prompts_share_novelty_block_and_bs3_adds_structured_checks():
    a3 = gt.build_v3("a3", "2026-11-22", write=False)
    bs3 = gt.build_v3("bs3", "2026-11-22", write=False)
    assert a3["instructions"][:3] == bs3["instructions"][:3]
    joined_a3 = " ".join(a3["instructions"])
    assert "testable change to the intervention itself" not in joined_a3
    assert "planned sample size" in joined_a3
    h_bs3 = bs3["answer_format"]["hypotheses"][0]
    assert "n_planned" in h_bs3["card"]["decisive_experiment"]
    assert {"critical_premise", "implementation_check"} <= set(h_bs3["check"])
    assert "disconfirming_result" in h_bs3["check"]["tested_before_T"]
