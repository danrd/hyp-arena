"""Run the graph end to end with the fake LLM (no real model calls): python -m hyparena.demo"""
from __future__ import annotations

from agent_kit.trace import render

from hyparena.context import Context, RunConfig
from hyparena.graph import build_graph
from hyparena.llm.fake import FakeLLMClient
from hyparena.llm.judges import JudgeSpec
from hyparena.state import initial_state

FAMILIES = ["gpt", "claude", "gemini", "qwen", "deepseek", "glm", "mimo", "grok", "muse"]


def main() -> None:
    pool = [JudgeSpec(f, f"{f}-fake-1") for f in FAMILIES]
    ctx = Context(client=FakeLLMClient(seed=0), judge_pool=pool,
                  generator_families=["gemini", "gpt", "claude"], cfg=RunConfig(max_cycles=3))
    graph = build_graph(ctx)
    final = graph.invoke(initial_state("Find tractable mechanisms of cellular ageing."),
                         config={"recursion_limit": 200})
    report = final["report"]
    print(f"cycles: {report['cycles']}, hypotheses: {len(final['hypotheses'])}, "
          f"matches: {len(final['matches'])}, front: {len(report['front'])}")
    print(render(report["tokens"]))


if __name__ == "__main__":
    main()
