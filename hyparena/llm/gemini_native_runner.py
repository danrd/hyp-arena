"""Gemini through its native `generateContent` endpoint (by default CometAPI's copy of it), with the `generate(prompt) -> str`
interface of llm_kit's runners. Not through the OpenAI-compatible endpoint: there CometAPI ignores every way of switching
Gemini 3.5 Flash's hidden reasoning off (`reasoning_effort` none or minimal, `thinking_config`, `thinking: disabled`:
70-100 reasoning tokens even for a one-word answer, 2026-10-30), and the reasoning is billed as output (about five times
the visible output of a card). The native endpoint honours `thinkingConfig.thinkingBudget: 0` (no thought tokens).

Generation settings read from the config: `max_tokens` (-> maxOutputTokens), `temperature`, `thinking_budget` (default 0)."""
from __future__ import annotations

import os
from typing import Any, Optional

DEFAULT_BASE_URL = "https://api.cometapi.com/v1beta"
DEFAULT_KEY_ENV = "COMET_API_KEY"


class GeminiNativeRunner:
    provider = "GeminiNative"

    def __init__(self, models: list[str], generation_kwargs: dict[str, Any], max_retries: int = 0,
                 timeout: float = 120.0, api_key_env: Optional[str] = None, base_url: Optional[str] = None, client=None):
        if len(models) != 1:
            raise ValueError("GeminiNativeRunner holds one model")
        self.model = models[0]
        self.last_model = self.model
        gen = dict(generation_kwargs)
        # Gemini 3.x: `thinking_level` (minimal / low / ...) is the control that works; since 2026-11-01 CometAPI's copy of
        # gemini-3.5-flash ignores `thinkingBudget: 0` (4200 thought tokens on a card, the output cut at maxOutputTokens)
        thinking = ({"thinkingLevel": str(gen["thinking_level"])} if gen.get("thinking_level")
                    else {"thinkingBudget": int(gen.get("thinking_budget", 0))})
        self.config: dict[str, Any] = {"thinkingConfig": thinking}
        if gen.get("max_tokens"):
            self.config["maxOutputTokens"] = int(gen["max_tokens"])
        if gen.get("temperature") is not None:
            self.config["temperature"] = float(gen["temperature"])
        self.url = f"{(base_url or DEFAULT_BASE_URL).rstrip('/')}/models/{self.model}:generateContent"
        key_env = api_key_env or DEFAULT_KEY_ENV
        self.key = os.environ.get(key_env)
        if not self.key:
            raise ValueError(f"{key_env} is not set")
        if client is None:
            import httpx
            client = httpx.Client(timeout=timeout)
        self._client = client
        self.last_usage: dict = {}

    def generate(self, prompt: str) -> str:
        r = self._client.post(self.url, headers={"x-goog-api-key": self.key, "Authorization": f"Bearer {self.key}"},
                              json={"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": self.config})
        if r.status_code != 200:
            raise RuntimeError(f"Error code: {r.status_code} - {r.text[:300]}")
        data = r.json()
        self.last_usage = data.get("usageMetadata") or {}
        self.last_model = data.get("modelVersion") or self.model     # the model that answered (Google may route a deprecated name)
        cand = (data.get("candidates") or [{}])[0]
        if cand.get("finishReason") == "MAX_TOKENS":          # a cut reply is an error, not a reply to parse
            raise RuntimeError(f"finishReason MAX_TOKENS (thought tokens {self.last_usage.get('thoughtsTokenCount', 0)}, "
                               f"output {self.last_usage.get('candidatesTokenCount', 0)})")
        parts = (cand.get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))

    def close(self) -> None:
        self._client.close()
