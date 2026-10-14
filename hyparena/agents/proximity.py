"""proximity: embeddings, near-duplicate merging and clusters over the active hypotheses."""
from __future__ import annotations

from hyparena.state import GraphState


def make_proximity(ctx):
    def proximity(state: GraphState) -> dict:
        active = [h for h in state.get("hypotheses", {}).values() if h.status == "active"]
        if not active:
            return {}
        texts = [((h.card.get("claim") + " ") if h.card else "") + h.text for h in active]
        emb = ctx.embedder.embed(texts)
        sim = emb @ emb.T
        updated, merged = {}, set()
        for j in range(len(active)):                # later hypotheses merge into earlier ones
            for i in range(j):
                if i not in merged and sim[i, j] >= ctx.cfg.dedup_threshold:
                    merged.add(j)
                    updated[active[j].id] = active[j].model_copy(
                        update={"status": "merged", "merged_into": active[i].id})
                    ctx.log.write({"event": "merged", "id": active[j].id, "into": active[i].id,
                                   "similarity": float(sim[i, j])})
                    break
        cluster: dict[int, int] = {}                 # greedy clustering over the kept ones
        for i in (i for i in range(len(active)) if i not in merged):
            for c in cluster:
                if sim[i, c] >= ctx.cfg.cluster_threshold:
                    cluster[i] = cluster[c]
                    break
            else:
                cluster[i] = len(set(cluster.values()))
            updated[active[i].id] = active[i].model_copy(update={"cluster": cluster[i]})
        return {"hypotheses": updated}
    return proximity
