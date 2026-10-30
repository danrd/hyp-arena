"""Build the LLM client and judge pool from configs/models.yaml.

Providers: the aggregators OpenRouter (free models) and CometAPI, and direct APIs: OpenAI, Anthropic
(official SDK, hyparena/llm/anthropic_runner.py), Google Gemini, DeepSeek, xAI and Mistral (their
OpenAI-compatible endpoints). Each provider reads its key from its usual environment variable unless the
spec names another (`api_key_env`); `base_url` reaches any other OpenAI-compatible service. With
`skip_missing_keys: true` a config lists several providers and uses those whose key is set. Paid specs are
refused unless the environment variable ALLOW_PAID=1 is set, so tests cannot spend money by accident."""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Literal, Optional

import yaml
from pydantic import BaseModel

from hyparena.llm.client import LLMClient, Reply, RunnerLLMClient
from hyparena.llm.judges import JudgeSpec

ALLOW_PAID_ENV = "ALLOW_PAID"
DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "models.yaml"


#: HTTP statuses that retrying cannot fix (bad request, auth, gated or unknown model).
_NON_RETRYABLE = re.compile(r"Error code: (400|401|403|404)\b")


class DeadlineExceeded(TimeoutError):
    pass


def call_with_deadline(fn: Callable[[], object], deadline: Optional[float]):
    """Run `fn` and give up after `deadline` seconds of wall-clock time. The HTTP client's own timeout
    measures silence between bytes, and a gateway that keeps the connection alive can defeat it. The
    abandoned call keeps running in a daemon thread; its result is ignored."""
    if not deadline:
        return fn()
    box: dict = {}

    def target():
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller
            box["error"] = e

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(deadline)
    if thread.is_alive():
        raise DeadlineExceeded(f"no answer within {deadline:.0f} s")
    if "error" in box:
        raise box["error"]
    return box["value"]


class PaidModelBlocked(RuntimeError):
    pass


class CallCapExceeded(RuntimeError):
    pass


#: Direct providers with an OpenAI-compatible chat endpoint: provider -> (base URL, key variable).
OPENAI_COMPATIBLE = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "google": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
}
#: Key variable of every provider when the spec names none.
KEY_ENV = {"openrouter": "OPENROUTER_API_KEY", "cometapi": "COMETAPI_KEY", "anthropic": "ANTHROPIC_API_KEY",
           "gemini_native": "COMET_API_KEY",
           **{p: env for p, (_, env) in OPENAI_COMPATIBLE.items()}}
Provider = Literal["openrouter", "cometapi", "openai", "anthropic", "google", "deepseek", "xai", "mistral", "gemini_native"]


class ModelSpec(BaseModel):
    family: str
    provider: Provider
    model: str
    tier: Literal["free", "paid"]
    enabled: bool = True
    api_key_env: Optional[str] = None
    base_url: Optional[str] = None        # another OpenAI-compatible endpoint (not for anthropic)
    generation: Optional[dict] = None     # overrides the global generation settings; a null value removes a key


class ProvidersConfig(BaseModel):
    rpm: float = 15
    timeout: float = 120
    max_retries: int = 1          # retries inside the OpenAI client, per request
    deadline: float = 150         # wall-clock seconds allowed per attempt
    concurrency: int = 4          # requests in flight at once, across all providers
    skip_missing_keys: bool = False   # use only the specs whose key variable is set (at least one)
    generation: dict = {"temperature": 0.7, "max_tokens": 2048}
    models: list[ModelSpec]


def paid_allowed() -> bool:
    return os.environ.get(ALLOW_PAID_ENV) == "1"


def load_config(path: str | Path = DEFAULT_CONFIG) -> ProvidersConfig:
    return ProvidersConfig(**yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def active_specs(cfg: ProvidersConfig, allow_paid: Optional[bool] = None) -> list[ModelSpec]:
    """Enabled specs, one per family. A paid spec without ALLOW_PAID raises instead of being skipped,
    so a mistake in the config is visible."""
    allow_paid = paid_allowed() if allow_paid is None else allow_paid
    specs = [s for s in cfg.models if s.enabled]
    if cfg.skip_missing_keys:
        keyed = [s for s in specs if os.environ.get(key_env(s))]
        if not keyed:
            raise ValueError("No API key is set for any model of this config; set one of: "
                             + ", ".join(sorted({key_env(s) for s in specs})))
        specs = keyed
    for s in specs:
        if s.tier == "paid" and not allow_paid:
            raise PaidModelBlocked(f"{s.family}: {s.model!r} is a paid model; set {ALLOW_PAID_ENV}=1 to use it.")
        if not s.model:
            raise ValueError(f"{s.family}: enabled but no model id is set.")
    families = [s.family for s in specs]
    if len(set(families)) != len(families):
        raise ValueError("Several enabled models share a family; the pool holds one model per family.")
    return specs


def key_env(spec: ModelSpec) -> str:
    return spec.api_key_env or KEY_ENV[spec.provider]


#: Roles whose family must not change: a judge's identity is what the independence rule is about.
NO_FALLBACK_ROLES = {"compare", "debate"}


class GuardedClient:
    """Wraps a client with a request-rate limit, a cap on concurrent and total calls, retries, and a
    wall-clock deadline per attempt. Safe to call from several threads.

    For roles other than judging, a family that keeps failing is replaced by the next family in
    `fallback_families`, skipping any family in `avoid` (for example the writer's family when the call
    is a review); the reply names the family that really answered, and provenance records it.

    Every attempt counts against the cap (a failed call still uses quota). After retries and fallbacks
    are spent, the reply is empty with `error` set, so the pipeline's own validation deals with it
    instead of the whole run crashing. Exceeding the cap or a daily limit raises CallCapExceeded."""

    def __init__(self, inner: LLMClient, *, rpm: float = 15, max_calls: Optional[int] = None,
                 retries: int = 2, backoff: float = 5.0, fallback_families: Optional[list[str]] = None,
                 deadline: Optional[float] = None, concurrency: int = 4,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.inner, self.max_calls, self.retries, self.backoff = inner, max_calls, retries, backoff
        self.fallback_families = list(fallback_families or [])
        self.deadline = deadline
        self._interval = 60.0 / rpm if rpm else 0.0
        self._sleep, self._clock = sleep, clock
        self._next_start = -1e18
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(max(1, concurrency))
        self.calls = 0
        self.failures = 0
        self.by_family: dict[str, int] = {}

    def _reserve(self, family: str) -> None:
        """Count the attempt against the cap and wait for its start slot under the rate limit."""
        with self._lock:
            if self.max_calls is not None and self.calls >= self.max_calls:
                raise CallCapExceeded(f"call cap of {self.max_calls} reached")
            self.calls += 1
            self.by_family[family] = self.by_family.get(family, 0) + 1
            start = max(self._clock(), self._next_start + self._interval)
            self._next_start = start
        wait = start - self._clock()
        if wait > 0:
            self._sleep(wait)

    def _failed(self) -> None:
        with self._lock:
            self.failures += 1

    def _try(self, role: str, family: str, prompt: str, attempts: int) -> tuple[Optional[Reply], str]:
        error = ""
        for attempt in range(attempts):
            self._reserve(family)
            try:
                with self._slots:
                    reply = call_with_deadline(
                        lambda: self.inner.call(role=role, family=family, prompt=prompt), self.deadline)
            except Exception as e:  # noqa: BLE001 - any provider failure is retried, then reported
                error = f"{type(e).__name__}: {e}"
                self._failed()
                if "per-day" in str(e) or "per_day" in str(e):
                    raise CallCapExceeded(f"daily limit reached: {str(e)[:200]}") from e
                if _NON_RETRYABLE.search(str(e)):
                    break
                self._sleep(self.backoff * (attempt + 1))
                continue
            if reply.text.strip():
                return reply, ""
            error = "empty reply"
            self._failed()
        return None, error

    def call(self, *, role: str, family: str, prompt: str, avoid: frozenset[str] = frozenset()) -> Reply:
        reply, error = self._try(role, family, prompt, self.retries + 1)
        if reply is not None:
            return reply
        if role not in NO_FALLBACK_ROLES:
            for other in (f for f in self.fallback_families if f != family and f not in avoid):
                reply, err = self._try(role, other, prompt, 1)
                if reply is not None:
                    return reply
                error += f" | {other}: {err}"
        return Reply(text="", family=family, model_id="", error=error)


def build_runner(s: ModelSpec, cfg: ProvidersConfig):
    """The runner of one spec: llm_kit's hosted runners for the OpenAI-compatible services, the Anthropic
    SDK for Claude."""
    gen = {k: v for k, v in {**cfg.generation, **(s.generation or {})}.items() if v is not None}
    common = dict(models=[s.model], generation_kwargs=gen, max_retries=cfg.max_retries, timeout=cfg.timeout)
    if s.provider == "anthropic":
        if s.base_url:
            raise ValueError(f"{s.family}: base_url is not used for anthropic")
        from hyparena.llm.anthropic_runner import AnthropicRunner      # lazy: needs the `anthropic` package
        return AnthropicRunner(**common, api_key_env=key_env(s))
    if s.provider == "gemini_native":                       # Gemini's own endpoint: hidden reasoning can be switched off
        from hyparena.llm.gemini_native_runner import GeminiNativeRunner
        return GeminiNativeRunner(**common, api_key_env=key_env(s), base_url=s.base_url)
    from llm_kit.llm_runtime import CometApiRunner, HostedRunner, OpenRouterRunner   # lazy: needs `openai`
    if s.provider in ("openrouter", "cometapi") and not s.base_url:
        cls = OpenRouterRunner if s.provider == "openrouter" else CometApiRunner
        return cls(**common, api_key_env=s.api_key_env)
    base_url = s.base_url or OPENAI_COMPATIBLE[s.provider][0]
    return HostedRunner(**common, base_url=base_url, api_key_env=key_env(s))


def build_runners(specs: list[ModelSpec], cfg: ProvidersConfig) -> dict[str, tuple[str, object]]:
    return {s.family: (s.model, build_runner(s, cfg)) for s in specs}


def build_client(config_path: str | Path = DEFAULT_CONFIG, *, max_calls: Optional[int] = None,
                 allow_paid: Optional[bool] = None, families: Optional[list[str]] = None
                 ) -> tuple[GuardedClient, list[JudgeSpec], ProvidersConfig]:
    """Guarded client plus the judge pool (one model per enabled family)."""
    cfg = load_config(config_path)
    specs = active_specs(cfg, allow_paid)
    if families:
        specs = [s for s in specs if s.family in families]
    inner = RunnerLLMClient(build_runners(specs, cfg))
    client = GuardedClient(inner, rpm=cfg.rpm, max_calls=max_calls, deadline=cfg.deadline,
                           concurrency=cfg.concurrency,
                           fallback_families=[s.family for s in specs])
    return client, [JudgeSpec(s.family, s.model) for s in specs], cfg
