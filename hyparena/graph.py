"""LangGraph assembly: supervisor-driven cycles of generate -> ... -> meta_review, then a report."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from hyparena.agents.evolve import make_evolve
from hyparena.agents.generate import make_generate
from hyparena.agents.meta_review import make_meta_review
from hyparena.agents.normalize import make_normalize
from hyparena.agents.parse_goal import make_parse_goal
from hyparena.agents.proximity import make_proximity
from hyparena.agents.report import make_report
from hyparena.agents.retrieve import make_retrieve
from hyparena.agents.review import make_review
from hyparena.agents.supervisor import make_supervisor
from hyparena.agents.tournament import make_tournament
from hyparena.context import Context
from hyparena.state import GraphState

CYCLE = ("generate", "normalize", "retrieve", "review", "proximity", "tournament", "evolve", "meta_review")


def build_graph(ctx: Context, checkpointer=None):
    g = StateGraph(GraphState)
    nodes = {"parse_goal": make_parse_goal, "supervisor": make_supervisor, "generate": make_generate,
             "normalize": make_normalize, "retrieve": make_retrieve, "review": make_review, "proximity": make_proximity,
             "tournament": make_tournament, "evolve": make_evolve, "meta_review": make_meta_review,
             "report": make_report}
    for name, factory in nodes.items():
        g.add_node(name, factory(ctx))
    g.add_edge(START, "parse_goal")
    g.add_edge("parse_goal", "supervisor")
    g.add_conditional_edges("supervisor", lambda s: s["next"], {"continue": CYCLE[0], "stop": "report"})
    for a, b in zip(CYCLE, CYCLE[1:]):
        g.add_edge(a, b)
    g.add_edge(CYCLE[-1], "supervisor")
    g.add_edge("report", END)
    return g.compile(checkpointer=checkpointer)
