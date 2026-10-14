"""LLM access. Every call returns a Reply that says which model actually answered."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


def estimate_tokens(text: str) -> int:
    """Rough estimate (about 4 characters per token). The toolkit's runners do not report usage yet."""
    return max(1, len(text) // 4)


@dataclass
class Reply:
    text: str
    family: str
    model_id: str                 # what answered (as configured; see docs/architecture.md, section 8)
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    error: str = ""              # set when the call failed and `text` is empty
    call_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


class LLMClient(Protocol):
    def call(self, *, role: str, family: str, prompt: str, avoid: frozenset[str] = frozenset()) -> Reply:
        """`avoid`: families that must not answer this call, even as a fallback."""
        ...


class RunnerLLMClient:
    """One runner per family. Each runner must hold a single model with no fallback chain,
    so that `model_version` is what really answered.

    `runners` maps family -> (model_version, runner), where `runner.generate(prompt) -> str`
    (llm_kit's `HostedRunner` and the other runners have this interface)."""

    def __init__(self, runners: Mapping[str, tuple[str, Any]]):
        self.runners = dict(runners)

    def call(self, *, role: str, family: str, prompt: str, avoid: frozenset[str] = frozenset()) -> Reply:
        model_version, runner = self.runners[family]
        started = time.perf_counter()
        text = runner.generate(prompt) or ""      # reasoning models can return no content
        return Reply(text=text, family=family, model_id=model_version,
                     tokens_in=estimate_tokens(prompt), tokens_out=estimate_tokens(text),
                     seconds=time.perf_counter() - started)
