"""Live checks against real models, free tier by default.

    python -m hyparena.live smoke            # one call per enabled family: does it answer, is the JSON valid
    python -m hyparena.live run              # a small graph run (one cycle)

Both stop at --max-calls (every attempt counts, retries included) so a free daily limit is not burnt.
Paid models in configs/models.yaml are refused unless ALLOW_PAID=1."""
from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from agent_kit.trace import render

from hyparena.context import Context, RunConfig
from hyparena.data import load_imported
from hyparena.graph import build_graph
from hyparena.llm.providers import DEFAULT_CONFIG, CallCapExceeded, build_client
from hyparena.llm.structured import parse_json
from hyparena.provenance import ProvenanceLog
from hyparena.rating import combined
from hyparena.state import AXES, PlanConfig, initial_state

GOAL = "Find mechanisms of cellular ageing that can be tested in vitro."
IMPORT_GOAL = "Identify the most promising and feasible hypotheses on the biology of ageing."
RUNS = Path(__file__).resolve().parents[1] / "runs"

TOY = ({"text": "Senescent fibroblasts spread senescence to neighbours through extracellular cGAMP; "
                "a cGAMP-binding trap in a 3D skin model should reduce new senescent cells.",
        "review_notes": "plausible; mechanism partly shown in tumour immunity"},
       {"text": "Ageing is caused by an unspecified accumulation of damage that a general "
                "rejuvenation treatment could reverse.",
        "review_notes": "vague; hard to test"})


def _context(args, **cfg_overrides) -> tuple[Context, object]:
    client, pool, _ = build_client(args.config, max_calls=args.max_calls)
    RUNS.mkdir(exist_ok=True)
    log = ProvenanceLog(RUNS / f"live-{datetime.now():%Y%m%d-%H%M%S}.jsonl")
    cfg = RunConfig(**cfg_overrides)
    ctx = Context(client=client, judge_pool=pool, generator_families=[j.family for j in pool],
                  cfg=cfg, log=log)
    print(f"families: {[j.family for j in pool]}  models: {[j.model_version for j in pool]}")
    print(f"log: {log.path}")
    return ctx, client


def smoke(args) -> None:
    ctx, client = _context(args)
    print(f"\n{'family':<18}{'model':<44}{'seconds':>8}{'json':>6}{'valid':>7}  note")
    for j in ctx.judge_pool:
        started = time.perf_counter()
        try:
            reply, _ = ctx.call(role="compare", family=j.family, template="compare", version="v1",
                                phase="rank", variables={"goal": GOAL, "plan": PlanConfig(), "feedback": {},
                                                         "first": TOY[0], "second": TOY[1],
                                                         "history_text": ""})
        except CallCapExceeded as e:
            print(f"stopped: {e}")
            break
        value = parse_json(reply.text)
        valid = bool(value) and all(value.get(ax) in (1, 2) for ax in AXES)
        note = reply.error or (f"picked {value.get('promise')}/{value.get('feasibility')}" if valid else reply.text[:50].replace("\n", " "))
        print(f"{j.family:<18}{j.model_version:<44}{time.perf_counter() - started:>8.1f}"
              f"{'yes' if value else 'no':>6}{'yes' if valid else 'no':>7}  {note}")
    print(f"\ncalls used: {client.calls} (failures: {client.failures}); by family: {client.by_family}")


def run(args) -> None:
    imported = load_imported(args.import_file, args.limit) if args.import_file else []
    gen = args.gen if args.gen is not None else (0 if imported else 4)
    goal = args.goal or (IMPORT_GOAL if imported else GOAL)
    if imported:
        p = imported[0].provenance
        print(f"imported: {len(imported)} hypotheses written by {p.family} / {p.model_version}")
    ctx, client = _context(args, max_cycles=1, gen_per_cycle=gen, evolve_per_cycle=1,
                           judges_per_match=1, extra_judges=0, matches_per_item=args.matches)
    graph = build_graph(ctx)
    try:
        final = graph.invoke(initial_state(goal, imported), config={"recursion_limit": 100})
    except CallCapExceeded as e:
        print(f"stopped: {e}; see the log for what was done")
        return
    h = final["hypotheses"]
    from collections import Counter
    print("\nstatus:", dict(Counter(x.status for x in h.values())))
    print("matches:", len(final["matches"]), " unparsable verdicts:",
          sum(1 for m in final["matches"] for v in m.judges if not v.parse_ok))
    viol = sum(1 for m in final["matches"] for v in m.judges
               if v.provenance.family in (h[m.a].provenance.family, h[m.b].provenance.family))
    print("judge independence violations:", viol)
    print(f"calls: {client.calls}, failures: {client.failures}, by family: {client.by_family}")
    print(render(final["report"]["tokens"]))
    ratings, plan = final["ratings"], final["plan"]
    active = [i for i, x in h.items() if x.status == "active"]
    if ratings.get("promise") and active:
        score, _ = combined(ratings, plan.axis_weights, active)
        print("\nranking (combined score; promise / feasibility; games):")
        for i in sorted(range(len(active)), key=lambda k: -score[k]):
            hid = active[i]
            title = h[hid].text.split("\n", 1)[0][:70]
            print(f"  {hid:<8}{score[i]:>6.2f}  {ratings['promise'][hid].score:>6.2f} / {ratings['feasibility'][hid].score:>6.2f}"
                  f"  {ratings['promise'][hid].games:>2}  [{h[hid].provenance.family}] {title}")
    for s in final["report"]["shown"][:3]:
        print(f"\n[{s['id']}] by {s['provenance']['family']} - promise {s['ratings']['promise']['score']:.2f}, "
              f"feasibility {s['ratings']['feasibility']['score']:.2f}\n{s['text'][:300]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["smoke", "run"])
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--max-calls", type=int, default=40)
    parser.add_argument("--goal", default=None)
    parser.add_argument("--gen", type=int, default=None, help="hypotheses generated in the run (default 4, or 0 with --import-file)")
    parser.add_argument("--import-file", default=None, help="dataset JSON of externally written hypotheses, e.g. data/chatgpt_hypotheses.json")
    parser.add_argument("--limit", type=int, default=None, help="with --import-file: use an evenly spaced sample of this size")
    parser.add_argument("--matches", type=float, default=1.0, help="tournament matches per active hypothesis")
    args = parser.parse_args()
    {"smoke": smoke, "run": run}[args.command](args)


if __name__ == "__main__":
    main()
