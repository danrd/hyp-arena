"""Provider routing (no network): which runner each provider gets, key variables, skipping missing keys,
and the Anthropic runner's request and refusal handling with a stub client."""
from types import SimpleNamespace

import pytest

from hyparena.llm import providers
from hyparena.llm.anthropic_runner import AnthropicRunner, ClaudeRefusal


def _cfg(models, **kw):
    return providers.ProvidersConfig(models=models, generation={"temperature": 0.2, "max_tokens": 4000}, **kw)


def test_openai_compatible_providers_get_their_endpoint(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    for provider, url in (("google", "generativelanguage.googleapis.com"), ("openai", "api.openai.com")):
        spec = providers.ModelSpec(family=provider, provider=provider, model="m", tier="paid")
        runner = providers.build_runner(spec, _cfg([spec]))
        assert url in runner.base_url and runner.api_key_env == providers.KEY_ENV[provider]


def test_base_url_reaches_another_service(monkeypatch):
    monkeypatch.setenv("MY_KEY", "x")
    spec = providers.ModelSpec(family="local", provider="openai", model="m", tier="paid",
                               base_url="http://localhost:8000/v1", api_key_env="MY_KEY")
    assert providers.build_runner(spec, _cfg([spec])).base_url == "http://localhost:8000/v1"


def test_missing_keys_are_skipped_only_when_asked(monkeypatch):
    for env in providers.KEY_ENV.values():
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    specs = [providers.ModelSpec(family=f, provider=f, model="m", tier="paid") for f in ("google", "anthropic")]
    assert [s.family for s in providers.active_specs(_cfg(specs, skip_missing_keys=True), allow_paid=True)] == ["anthropic"]
    assert len(providers.active_specs(_cfg(specs), allow_paid=True)) == 2
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        providers.active_specs(_cfg(specs, skip_missing_keys=True), allow_paid=True)


class _Stub:
    def __init__(self, response):
        self.sent = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: (self.sent.append(kw), response)[1]))


def _response(stop="end_turn", model="claude-opus-5-5"):
    return SimpleNamespace(stop_reason=stop, model=model, stop_details=SimpleNamespace(category="cyber"),
                           content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text="ok")])


def test_anthropic_request_has_no_sampling_parameters():
    stub = _Stub(_response(model="claude-opus-4-8"))
    r = AnthropicRunner(["claude-opus-5-5"], {"temperature": 0.2, "max_tokens": 4000, "reasoning_effort": "minimal"}, client=stub)
    assert r.generate("hi") == "ok" and r.last_model == "claude-opus-4-8"
    sent = stub.sent[0]
    assert "temperature" not in sent and sent["max_tokens"] == 16000 and sent["output_config"] == {"effort": "low"}
    assert sent["fallbacks"] == "default" and sent["betas"] == ["server-side-fallback-2026-07-01"]
    stub = _Stub(_response())
    AnthropicRunner(["claude-haiku-5-5"], {}, client=stub).generate("hi")
    assert "fallbacks" not in stub.sent[0] and "output_config" not in stub.sent[0]


def test_anthropic_refusal_raises():
    with pytest.raises(ClaudeRefusal, match="cyber"):
        AnthropicRunner(["claude-opus-5-5"], {}, client=_Stub(_response(stop="refusal"))).generate("hi")


def test_direct_config_loads():
    cfg = providers.load_config("configs/v2-direct.yaml")
    assert cfg.skip_missing_keys and {s.provider for s in cfg.models} == {"google", "openai", "anthropic"}


def test_gemini_native_runner_switches_reasoning_off_and_drops_thought_parts(monkeypatch):
    from hyparena.llm.gemini_native_runner import GeminiNativeRunner

    class Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "hidden", "thought": True}, {"text": "OK"}]}}],
                    "usageMetadata": {"candidatesTokenCount": 1}}

    class Client:
        def post(self, url, headers, json):
            self.sent = (url, json)
            return Resp()

    monkeypatch.setenv("COMET_API_KEY", "x")
    c = Client()
    r = GeminiNativeRunner(["gemini-3.5-flash"], {"max_tokens": 4000, "temperature": 0.2}, client=c)
    assert r.generate("hi") == "OK"
    url, body = c.sent
    assert url.endswith("/models/gemini-3.5-flash:generateContent")
    assert body["generationConfig"] == {"thinkingConfig": {"thinkingBudget": 0}, "maxOutputTokens": 4000, "temperature": 0.2}


def test_candidate_configs_of_the_normalizer_check_load():
    from hyparena.llm.providers import load_config
    a = load_config("configs/v2-flash-gemini-nothink.yaml")
    assert [(m.family, m.provider) for m in a.models] == [("google", "gemini_native"), ("deepseek", "cometapi")]
    assert [m.family for m in load_config("configs/v2-flash-deepseek-norm.yaml").models] == ["deepseek"]
