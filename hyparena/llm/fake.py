"""A deterministic stand-in LLM, enough to exercise the graph shape (no real model behind it)."""
from __future__ import annotations

import json
import random
import threading
import zlib

from hyparena.llm.client import Reply, estimate_tokens

TOPICS = [
    "senescent fibroblasts secrete inflammatory cytokines that propagate damage to neighbours",
    "mitochondrial heteroplasmy drifts upward after repeated rounds of selective mitophagy",
    "nucleolar condensate permeability declines with replicative age in budding yeast",
    "thymic medulla architecture loses antigen presenting niches during involution",
    "chromatin remodelling reactivates silent transposons in ageing hepatocytes",
    "lysosomal repair kinetics limit nuclear delivery of damage response proteins",
    "microglial lipid droplets trap cholesterol until export capacity recovers",
    "muscle stem cell niche stress relaxation slows regeneration in old tissue",
]


def _example_keys(prompt: str) -> dict:
    """The JSON skeleton the prompt asks for (its last line that parses as a JSON object)."""
    for line in reversed(prompt.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
    return {}


class FakeLLMClient:
    """Returns canned, parsable replies per role. Quality signals are random, not real."""

    def __init__(self, seed: int = 0):
        self.seed = seed
        self.n = 0
        self._lock = threading.Lock()

    def call(self, *, role: str, family: str, prompt: str, avoid: frozenset[str] = frozenset()) -> Reply:
        with self._lock:
            self.n += 1
            n = self.n
        rng = random.Random(self.seed * 1_000_003 + zlib.crc32(prompt.encode()) + n)
        text = getattr(self, f"_{role}")(rng, prompt, n)
        return Reply(text=text, family=family, model_id=f"fake-{family}-1",
                     tokens_in=estimate_tokens(prompt), tokens_out=estimate_tokens(text))

    def _parse_goal(self, rng, prompt, n):
        return json.dumps({"preferences": "novel, testable mechanisms of ageing",
                           "attributes": ["novelty", "feasibility"],
                           "constraints": ["must be testable in vitro"]})

    def _generate(self, rng, prompt, n):
        i = n
        return (f"Hypothesis {i}: {TOPICS[i % len(TOPICS)]}, variant {i // len(TOPICS)}. "
                f"Prediction: perturbing it changes the readout. Test: a controlled experiment. "
                f"It would be refuted if the readout does not change.")

    _evolve = _generate

    def _normalize(self, rng, prompt, n):
        skeleton = _example_keys(prompt)
        card = {k: ([f"{k} item"] if isinstance(v, list) else f"A {k}.") for k, v in skeleton.items()}
        card["search_queries"] = ["ageing mechanism", "senescence"]
        if "was not accepted" not in prompt and rng.random() < 0.3 and skeleton:
            card[next(iter(skeleton))] = ""          # exercises the refine loop
        return json.dumps(card)

    def _review_initial(self, rng, prompt, n):
        return json.dumps({"correctness": rng.randint(3, 9), "novelty": rng.randint(2, 9),
                           "quality": rng.randint(3, 9), "safety_ok": True,
                           "notes": ["plausible but unverified"]})

    def _review_full(self, rng, prompt, n):
        return json.dumps({"correctness": rng.randint(3, 9), "novelty": rng.randint(2, 9),
                           "quality": rng.randint(3, 9), "known_aspects": "some prior work",
                           "citations": [], "notes": ["checked against retrieved passages"]})

    def _review_deep(self, rng, prompt, n):
        return json.dumps({"assumptions": [{"text": "assumption", "correct": True}],
                           "fundamental_flaw": rng.random() < 0.1, "notes": ["no fatal flaw found"]})

    def _compare(self, rng, prompt, n):
        keys = [k for k in _example_keys(prompt) if k != "rationale"] or ["promise", "feasibility"]
        return json.dumps({**{k: rng.choice([1, 2]) for k in keys}, "rationale": "fake rationale"})

    def _debate(self, rng, prompt, n):
        return ("Turn 1: summary. Turn 2: objections. Turn 3: conclusion.\n"
                + self._compare(rng, prompt, n))

    def _leakage(self, rng, prompt, n):
        return json.dumps({"result": rng.choice(["supported", "refuted", "unknown"]),
                           "confidence": round(rng.random(), 2), "what_you_remember": "fake"})

    def _research_overview(self, rng, prompt, n):
        return "## Research overview (fake)\n\n- Area 1: example direction.\n- Area 2: another direction."

    def _meta_review(self, rng, prompt, n):
        return json.dumps({"generate": "State a refutation condition.", "review": "Check citations.",
                           "compare": "Do not prefer longer text.", "evolve": "Keep claims testable."})
