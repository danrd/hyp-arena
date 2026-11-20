import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.whole_system import codex_benchmark as bench


def test_auc_and_accuracy_use_same_trials_with_half_credit_for_ties():
    cases = [{"id": "positive", "label": 1}, {"id": "negative", "label": 0}, {"id": "missing", "label": 1}]
    predictions = {"system": {"positive": {"score": 0.2}, "negative": {"score": 0}, "missing": {"score": None}},
                   "direct": {"positive": {"score": 0.5}, "negative": {"score": 0.5}, "missing": {"score": 0.99}}}
    summary = bench.summarize(cases, predictions, draws=10)
    assert summary["scored"] == {"system": 2, "direct": 3}
    assert summary["n_paired"] == 2
    assert summary["metrics"] == {"system_auc": 1, "system_accuracy": 1, "direct_auc": 0.5, "direct_accuracy": 0.5,
                                  "delta_auc": 0.5, "delta_accuracy": 0.5}
    assert summary["ci95"]["delta_auc"] == [0.5, 0.5]
    assert bench.auc([(1.0, 1)]) is None


@pytest.mark.parametrize("tool_used", [False, True])
def test_direct_uses_isolated_exec_and_rejects_tool_events(monkeypatch, tool_used):
    def fake_exec(command, *, input, cwd, **options):
        assert not cwd.is_relative_to(bench.ROOT)
        assert '--ignore-user-config' in command
        assert 'web_search="disabled"' in command
        assert "shell_tool" in command
        assert "Version of the trial" in input and "2020-01-01" in input
        schema = Path(command[command.index("--output-schema") + 1])
        assert json.loads(schema.read_text()) == bench.PROBABILITY_SCHEMA
        Path(command[command.index("--output-last-message") + 1]).write_text('{"p_positive": 0.7}')
        event = {"type": "item.completed", "item": {"type": "web_search" if tool_used else "agent_message"}}
        usage = {"type": "turn.completed", "usage": {"input_tokens": 20, "output_tokens": 5}}
        return subprocess.CompletedProcess(command, 0, f"{json.dumps(event)}\n{json.dumps(usage)}\n", "")

    monkeypatch.setattr(bench.subprocess, "run", fake_exec)
    client = bench.Codex("codex", "model-for-test", "medium", 3)
    if tool_used:
        with pytest.raises(RuntimeError, match="unexpected Codex item"):
            bench.predict_direct(client, "Version of the trial", "2020-01-01")
    else:
        assert bench.predict_direct(client, "Version of the trial", "2020-01-01") == {
            "score": 0.7, "calls": 1, "input_tokens": 20, "output_tokens": 5}


def test_resume_does_not_replay_the_completed_arm(monkeypatch, tmp_path):
    cases = [{"id": "trial", "text": "Example trial", "as_of": "2020-01-01", "label": 1,
              "flagged": False, "b2_clean": False}]
    result = {"score": 0.7, "calls": 1, "input_tokens": 20, "output_tokens": 5}
    monkeypatch.setattr(bench, "load_cases", lambda path: (cases, "texts-hash"))
    monkeypatch.setenv("ALLOW_PAID", "1")
    monkeypatch.setattr(sys, "argv", ["bench", "run", "--model", "model-for-test", "--out", str(tmp_path)])
    monkeypatch.setattr(bench, "predict_system", lambda *args: result)

    def interrupted(*args):
        raise RuntimeError("interrupted")

    monkeypatch.setattr(bench, "predict_direct", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        bench.main()
    assert json.loads((tmp_path / "predictions.json").read_text())["predictions"]["system"] == {"trial": result}

    monkeypatch.setattr(bench, "predict_system", interrupted)
    monkeypatch.setattr(bench, "predict_direct", lambda *args: result)
    bench.main()
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["pending"] == {"system": 0, "direct": 0}
    assert report["all"]["n_paired"] == 1


def test_system_uses_injected_client_and_date(monkeypatch):
    from hyparena import pipeline

    def run(texts, **options):
        assert texts == ["Example trial"]
        assert options["as_of"] == options["llm_client"].inner.as_of == "2020-01-01"
        assert options["normalizer_family"] == options["verifiers"][0] == "codex"
        assert options["llm_client"].max_calls == 3
        return {"items": [{"outcome": "normalization_failed"}]}

    monkeypatch.setattr(pipeline, "run", run)
    client = bench.Codex("codex", "model-for-test", "medium", 3)
    result = bench.predict_system(client, "Example trial", "2020-01-01", bench.ROOT / "configs/v3-flash-n10.yaml", 3)
    assert result["score"] is None
