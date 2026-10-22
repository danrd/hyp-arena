"""Claude through the official Anthropic SDK (Messages API), with the `generate(prompt) -> str` interface of
llm_kit's runners. Not through an OpenAI-compatible shim: current Claude models reject sampling parameters
(`temperature`, `top_p`), think adaptively by default and take their depth from `output_config.effort`.

Generation settings read from the config: `max_tokens` (thinking counts against it, so at least
`MIN_MAX_TOKENS`), `effort` (or `reasoning_effort`, mapped: minimal -> low); sampling parameters are dropped.
On a safety decline the request is re-run server-side on a fallback model (`fallbacks: "default"`) for the
models that support it; a final refusal raises, so the guarded client retries or falls back to another
family. The model that really answered is kept in `last_model`."""
from __future__ import annotations

import os
from typing import Any, Optional

DEFAULT_KEY_ENV = "ANTHROPIC_API_KEY"
MIN_MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
EFFORTS = ("low", "medium", "high", "xhigh", "max")


class ClaudeRefusal(RuntimeError):
    pass


class AnthropicRunner:
    provider = "Anthropic"

    def __init__(self, models: list[str], generation_kwargs: dict[str, Any], max_retries: int = 2,
                 timeout: float = 120.0, api_key_env: Optional[str] = None, client=None):
        if len(models) != 1:
            raise ValueError("AnthropicRunner holds one model")
        self.model = models[0]
        self.last_model = self.model
        gen = dict(generation_kwargs)
        self.max_tokens = max(int(gen.get("max_tokens") or gen.get("max_completion_tokens") or 0), MIN_MAX_TOKENS)
        effort = gen.get("effort") or gen.get("reasoning_effort")
        effort = "low" if effort == "minimal" else effort
        self.effort = effort if effort in EFFORTS else None
        fallbacks = gen.get("fallbacks", "default")
        self.fallbacks = fallbacks if fallbacks and self.model in FALLBACK_MODELS else None
        if client is None:
            import anthropic
            key_env = api_key_env or DEFAULT_KEY_ENV
            key = os.environ.get(key_env)
            if not key:
                raise ValueError(f"{key_env} is not set")
            client = anthropic.Anthropic(api_key=key, max_retries=max_retries, timeout=timeout)
        self._client = client

    def generate(self, prompt: str) -> str:
        kwargs: dict[str, Any] = {"model": self.model, "max_tokens": self.max_tokens,
                                  "messages": [{"role": "user", "content": prompt}]}
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        if self.fallbacks:
            kwargs.update(betas=[FALLBACK_BETA], fallbacks=self.fallbacks)
        response = self._client.beta.messages.create(**kwargs)
        self.last_model = getattr(response, "model", None) or self.model
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise ClaudeRefusal(f"{self.model} declined ({getattr(details, 'category', None) or 'no category'})")
        return "".join(block.text for block in response.content if block.type == "text")

    def close(self) -> None:
        pass
