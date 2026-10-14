"""Run-time dependencies shared by all nodes: LLM client, tools, tracer, provenance log, config."""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any, Optional

from agent_kit import trace
from agent_kit.trace import Tracer

from hyparena.llm.client import LLMClient, Reply, estimate_tokens
from hyparena.llm.judges import JudgeSpec, LineageMode
from hyparena.llm.prompts import render
from hyparena.provenance import ProvenanceLog
from hyparena.state import Provenance
from hyparena.tools.embed import Embedder, HashingEmbedder
from hyparena.tools.search import NullSearch, SearchTool

#: Phases of this project's trace table (agent_kit.trace.PHASES is replaced with these).
PHASES = ("generate", "normalize", "review", "proximity", "rank", "debate", "evolve", "meta", "other")


@dataclass
class RunConfig:
    lineage_mode: LineageMode = "writer"
    seed: int = 0
    # budget
    max_cycles: int = 3
    max_tokens: int = 2_000_000          # estimated tokens
    # generation and evolution
    gen_per_cycle: int = 6
    evolve_per_cycle: int = 3
    normalize_rounds: int = 2
    # review thresholds
    min_correctness: float = 4.0
    min_novelty: float = 3.0
    # proximity
    dedup_threshold: float = 0.92
    cluster_threshold: float = 0.5
    # tournament
    matches_per_item: float = 2.0         # matches per active hypothesis in each cycle
    top_frac: float = 0.1
    swiss_share: float = 0.2
    z: float = 2.0
    judges_per_match: int = 2
    extra_judges: int = 1
    debate_top: int = 5                   # pairs inside the current top-N are judged by debate
    # report
    report_size: int = 10


@dataclass
class Context:
    client: LLMClient
    judge_pool: list[JudgeSpec]
    generator_families: list[str]
    cfg: RunConfig = field(default_factory=RunConfig)
    search: SearchTool = field(default_factory=NullSearch)
    embedder: Embedder = field(default_factory=HashingEmbedder)
    tracer: Tracer = field(default_factory=Tracer)
    log: ProvenanceLog = field(default_factory=ProvenanceLog)
    rng: random.Random = field(init=False)
    _rotation: dict[str, int] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.cfg.seed)
        trace.PHASES = PHASES

    def call(self, *, role: str, family: str, template: str, version: str,
             variables: dict[str, Any], phase: str, strategy: str = "") -> tuple[Reply, Provenance]:
        """Render a prompt, call the family's model inside a trace span, log and return the reply."""
        prompt = render(template, version, **variables)
        with self.tracer.span(phase, role, tokens_in=estimate_tokens(prompt)) as span:
            reply = self.client.call(role=role, family=family, prompt=prompt)
            span.tokens_out = reply.tokens_out
        prov = Provenance(family=reply.family, model_version=reply.model_id, role=role,
                          template=template, prompt_version=version, strategy=strategy,
                          call_id=reply.call_id)
        self.log.write({"event": "call", **prov.model_dump(), "phase": phase,
                        "tokens_in": reply.tokens_in, "tokens_out": reply.tokens_out,
                        "prompt_sha1": hashlib.sha1(prompt.encode()).hexdigest()[:12]})
        return reply, prov

    def tokens_used(self) -> int:
        return int(sum(row["tokens_in"] + row["tokens_out"] for row in self.tracer.summary().values()))

    def rotate(self, kind: str, options: list) -> Any:
        """Round-robin over `options`, independently per `kind`."""
        i = self._rotation.get(kind, 0)
        self._rotation[kind] = i + 1
        return options[i % len(options)]

    def utility_family(self) -> str:
        """Family used for bookkeeping calls (goal parsing, normalization, meta-review)."""
        return self.generator_families[0]
