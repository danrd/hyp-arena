"""supervisor: decides whether to run another cycle or stop."""
from __future__ import annotations

from hyparena.state import GraphState


def make_supervisor(ctx):
    def supervisor(state: GraphState) -> dict:
        cycle, history = state.get("cycle", 0), state.get("top_history", [])
        reason = None
        if cycle >= ctx.cfg.max_cycles:
            reason = "max_cycles"
        elif ctx.tokens_used() >= ctx.cfg.max_tokens:
            reason = "token_budget"
        elif cycle >= 2 and len(history) >= 2 and set(history[-1]) == set(history[-2]):
            reason = "top_stable"
        if reason:
            ctx.log.write({"event": "stop", "reason": reason, "cycle": cycle})
            return {"next": "stop"}
        return {"next": "continue", "cycle": cycle + 1}
    return supervisor
