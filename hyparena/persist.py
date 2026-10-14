"""Persistent graph state (Co-Scientist's context memory): a LangGraph SQLite checkpointer.

The state after every node is written to the database under a thread id. A run that stopped (crash,
call cap, daily limit) continues from its last checkpoint with `graph.invoke(None, config)` and the
same thread id. What lives outside the graph state starts afresh on resume: the trace, the call
counters and the round-robin positions of the run context."""
from __future__ import annotations

import sqlite3
from pathlib import Path


#: State models the checkpoint may rebuild; LangGraph refuses unlisted types in strict mode.
STATE_TYPES = [("hyparena.state", name) for name in
               ("PlanConfig", "Criterion", "Hypothesis", "Provenance", "Card", "Evidence", "Review",
                "JudgeVerdict", "Match", "Rating")]


def sqlite_checkpointer(path: str | Path):
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from langgraph.checkpoint.sqlite import SqliteSaver   # package: langgraph-checkpoint-sqlite
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(str(path), check_same_thread=False),
                       serde=JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES))


def run_config(thread_id: str, recursion_limit: int = 200) -> dict:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}


def has_checkpoint(graph, thread_id: str) -> bool:
    return graph.get_state(run_config(thread_id)).values != {}
