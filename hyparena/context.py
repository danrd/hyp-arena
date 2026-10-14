"""Run-time dependencies shared by all nodes: LLM client, tools, tracer, provenance log, config."""
from __future__ import annotations

import hashlib
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, TypeVar

from agent_kit import trace
from agent_kit.trace import Tracer

from hyparena.llm.client import LLMClient, Reply, estimate_tokens
from hyparena.llm.judges import JudgeSpec, LineageMode
from hyparena.llm.prompts import render
from hyparena.provenance import ProvenanceLog
from hyparena.schema import CardSchema, CriteriaSet, load_card_schema, load_criteria
from hyparena.state import Provenance
from hyparena.tools.embed import Embedder, HashingEmbedder
from hyparena.tools.retractions import RetractionIndex
from hyparena.tools.search import NullSearch, SearchTool

T = TypeVar("T")
R = TypeVar("R")

#: Phases of this project's trace table (agent_kit.trace.PHASES is replaced with these).
PHASES = ("generate", "normalize", "retrieve", "review", "proximity", "rank", "debate", "evolve", "meta", "other")


@dataclass
class RunConfig:
    lineage_mode: LineageMode = "writer"
    step: str = ""                       # ablation ladder step (hyparena/ladder.py), recorded in results
    # "full": our method. "coscientist": baseline as in the paper (one Elo, holistic verdict, judges see
    # only text and reviews, pairing by newness/top/similarity); combine with lineage_mode="none".
    rating: str = "bt"                   # "bt" (Bradley-Terry with intervals) or "elo" (Co-Scientist)
    pairing: str = "bt"                  # "bt" (elimination + Swiss) or "coscientist" (new/top/similar first)
    judge_view: str = "full"             # "full" (card + evidence + criteria) or "coscientist"
    seed: int = 0
    workers: int = 8                     # parallel LLM tasks inside a node (the client caps requests in flight)
    # budget
    max_cycles: int = 3
    max_tokens: int = 2_000_000          # estimated tokens
    # generation and evolution
    gen_per_cycle: int = 6
    evolve_per_cycle: int = 3
    normalize_rounds: int = 2
    # evidence
    as_of: Optional[str] = None          # ISO date: only evidence published on or before it (backtests)
    evidence_per_query: int = 5
    evidence_max: int = 10               # kept per hypothesis
    evidence_to_judges: int = 5          # shown to judges per hypothesis
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
    retractions: Optional[RetractionIndex] = None     # marks retracted evidence (see tools/retractions.py)
    criteria: CriteriaSet = field(default_factory=load_criteria)
    card_schema: CardSchema = field(default_factory=load_card_schema)
    rng: random.Random = field(init=False)
    _rotation: dict[str, int] = field(default_factory=dict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.cfg.seed)
        trace.PHASES = PHASES

    def rng_for(self, *key: Any) -> random.Random:
        """A generator that depends only on the seed and `key`, so parallel tasks stay reproducible."""
        return random.Random(":".join(str(k) for k in (self.cfg.seed, *key)))

    def map(self, fn: Callable[[T], R], items: Iterable[T]) -> list[R]:
        """`fn` over `items` on a thread pool, results in input order. The first exception is raised."""
        items = list(items)
        if self.cfg.workers <= 1 or len(items) <= 1:
            return [fn(x) for x in items]
        with ThreadPoolExecutor(max_workers=min(self.cfg.workers, len(items))) as pool:
            return list(pool.map(fn, items))

    def call(self, *, role: str, family: str, template: str, version: str,
             variables: dict[str, Any], phase: str, strategy: str = "",
             avoid: Iterable[str] = ()) -> tuple[Reply, Provenance]:
        """Render a prompt, call the family's model inside a trace span, log and return the reply.
        `avoid`: families that must not answer, even if the client falls back to another family."""
        prompt = render(template, version, **variables)
        with self.tracer.span(phase, role, tokens_in=estimate_tokens(prompt)) as span:
            reply = self.client.call(role=role, family=family, prompt=prompt, avoid=frozenset(avoid))
            span.tokens_out = reply.tokens_out
        if reply.error:
            self.log.write({"event": "call_failed", "role": role, "family": family, "error": reply.error[:300]})
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
        with self._lock:
            i = self._rotation.get(kind, 0)
            self._rotation[kind] = i + 1
        return options[i % len(options)]

    def utility_family(self) -> str:
        """Family for bookkeeping calls (goal parsing, normalization, meta-review); rotates so that
        no single provider carries them all."""
        return self.rotate("utility", self.generator_families)
