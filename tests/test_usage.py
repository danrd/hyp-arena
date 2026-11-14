"""Resource accounting: prices from configs/prices.yaml, stages from the call log, the USD cap of the guarded client."""
import pytest

from hyparena.llm.client import Reply
from hyparena.llm.providers import CallCapExceeded, GuardedClient
from hyparena.usage import cost, estimate_tokens, stage_of, summarize


def test_cost_and_peak_hours():
    assert cost("gemini-3.5-flash", 1_000_000, 100_000) == pytest.approx(1.5 + 0.9)
    off = cost("deepseek-v4.1-flash-1017", 1_000_000, 0, "deepseek", "2026-11-13T12:00:00+00:00")   # Friday, off-peak
    peak = cost("deepseek-v4.1-flash-1017", 1_000_000, 0, "deepseek", "2026-11-13T07:30:00+00:00")  # Friday 07:30 UTC
    weekend = cost("deepseek-v4.1-flash-1017", 1_000_000, 0, "deepseek", "2026-11-14T07:30:00+00:00")
    assert off == pytest.approx(0.15) and peak == pytest.approx(0.30) and weekend == pytest.approx(0.15)
    assert cost("some-unpriced-model", 10, 10) is None
    assert cost("", 1_000_000, 0, "google") == pytest.approx(1.5)          # an old log with the family only


def test_stages_and_summary():
    calls = [{"template": "normalize_card/v15", "model": "gemini-3.5-flash", "tokens_in": 1000, "tokens_out": 100, "seconds": 2},
             {"role": "verify_claim", "template": "estimand/v1", "model": "gemini-3.5-flash", "tokens_in": 10, "tokens_out": 1},
             {"role": "verify_claim", "template": "verify_claim/v13", "model": "x-unpriced", "tokens_in": 5, "tokens_out": 5}]
    assert [stage_of(c) for c in calls] == ["card", "endpoint", "reading"]
    s = summarize(calls)
    assert list(s["stages"]) == ["card", "reading", "endpoint"] and s["total"]["calls"] == 3
    assert s["unpriced"] == ["x-unpriced"] and s["stages"]["card"]["usd"] == pytest.approx(0.0024)


def test_estimate_tokens_by_script():
    assert estimate_tokens("a" * 36) == 10 and estimate_tokens("б" * 26) == 10


class _Inner:
    def call(self, *, role, family, prompt, avoid=frozenset()):
        return Reply(text="{}", family=family, model_id="gemini-3.5-flash", tokens_in=100_000, tokens_out=10_000)


def test_usd_cap_stops_the_run():
    g = GuardedClient(_Inner(), rpm=0, max_usd=0.5, sleep=lambda s: None)
    n = 0
    with pytest.raises(CallCapExceeded):
        for _ in range(10):
            g.call(role="normalize_card", family="google", prompt="x")
            n += 1
    # 0.24 USD a call; the cap is checked before a call, so the call that crosses it finishes and the next is refused
    assert n == 3 and g.usd == pytest.approx(0.72) and g.tokens_in == 300_000
