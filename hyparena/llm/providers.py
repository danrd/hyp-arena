"""Build the LLM client and judge pool from configs/models.yaml.

Free models go through OpenRouter, paid ones through CometAPI. Paid specs are refused unless the
environment variable ALLOW_PAID=1 is set, so tests cannot spend money by accident."""
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


class ModelSpec(BaseModel):
    family: str
    provider: Literal["openrouter", "cometapi"]
    model: str
    tier: Literal["free", "paid"]
    enabled: bool = True
    api_key_env: Optional[str] = None
    generation: Optional[dict] = None     # overrides the global generation settings; a null value removes a key


class ProvidersConfig(BaseModel):
    rpm: float = 15
    timeout: float = 120
    max_retries: int = 1          # retries inside the OpenAI client, per request
    deadline: float = 150         # wall-clock seconds allowed per attempt
    concurrency: int = 4          # requests in flight at once, across all providers
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
    for s in specs:
        if s.tier == "paid" and not allow_paid:
            raise PaidModelBlocked(f"{s.family}: {s.model!r} is a paid model; set {ALLOW_PAID_ENV}=1 to use it.")
        if not s.model:
            raise ValueError(f"{s.family}: enabled but no model id is set.")
    families = [s.family for s in specs]
    if len(set(families)) != len(families):
        raise ValueError("Several enabled models share a family; the pool holds one model per family.")
    return specs


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


def build_runners(specs: list[ModelSpec], cfg: ProvidersConfig) -> dict[str, tuple[str, object]]:
    from llm_kit.llm_runtime import CometApiRunner, OpenRouterRunner   # lazy: needs the `openai` package
    classes = {"openrouter": OpenRouterRunner, "cometapi": CometApiRunner}
    runners = {}
    for s in specs:
        gen = {k: v for k, v in {**cfg.generation, **(s.generation or {})}.items() if v is not None}
        runner = classes[s.provider](models=[s.model], generation_kwargs=gen,
                                     max_retries=cfg.max_retries, timeout=cfg.timeout, api_key_env=s.api_key_env)
        runners[s.family] = (s.model, runner)
    return runners


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
