"""Live checks against real models, free tier by default.

    python -m hyparena.live smoke            # one call per enabled family: does it answer, is the JSON valid
    python -m hyparena.live run              # a small graph run (one cycle)

Both stop at --max-calls (every attempt counts, retries included) so a free daily limit is not burnt.
Paid models in configs/models.yaml are refused unless ALLOW_PAID=1."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from agent_kit.trace import render

from hyparena.context import Context, RunConfig
from hyparena.data import dataset_options, load_imported
from hyparena.graph import build_graph
from hyparena.ladder import LADDER, MODES
from hyparena.llm.fake import FakeLLMClient
from hyparena.llm.judges import JudgeSpec
from hyparena.llm.providers import DEFAULT_CONFIG, CallCapExceeded, GuardedClient, build_client, load_config
from hyparena.llm.structured import parse_json
from hyparena.persist import has_checkpoint, run_config, sqlite_checkpointer
from hyparena.provenance import ProvenanceLog
from hyparena.rating import combined
from hyparena.schema import CONFIGS, load_card_schema, load_criteria, verdict_example
from hyparena.state import PlanConfig, initial_state
from hyparena.tools.registry import SOURCES, build_search
from hyparena.tools.retractions import DEFAULT as RW_DEFAULT, RetractionIndex

GOAL = "Find mechanisms of cellular ageing that can be tested in vitro."
IMPORT_GOAL = "Identify the most promising and feasible hypotheses on the biology of ageing."
RUNS = Path(__file__).resolve().parents[1] / "runs"

TOY = ({"text": "Senescent fibroblasts spread senescence to neighbours through extracellular cGAMP; "
                "a cGAMP-binding trap in a 3D skin model should reduce new senescent cells.",
        "review_notes": "plausible; mechanism partly shown in tumour immunity", "card": {}, "gaps": [], "evidence": []},
       {"text": "Ageing is caused by an unspecified accumulation of damage that a general "
                "rejuvenation treatment could reverse.",
        "review_notes": "vague; hard to test", "card": {}, "gaps": ["decisive_experiment", "falsifiable_implications"],
        "evidence": []})


def _context(args, **cfg_overrides) -> tuple[Context, object]:
    step = LADDER[args.ladder or MODES[args.mode]]
    if args.fake:
        # No model calls: the fake LLM with the configured families (for testing the experiment machinery).
        specs = [s for s in load_config(args.config).models if s.enabled]
        pool = [JudgeSpec(s.family, f"fake-{s.model}") for s in specs]
        client = GuardedClient(FakeLLMClient(args.seed), rpm=0, max_calls=args.max_calls)
    else:
        client, pool, _ = build_client(args.config, max_calls=args.max_calls)
    if step.single_family:
        pool = pool[:1]
    criteria_path = args.criteria if args.criteria_given else str(CONFIGS / step.criteria)
    cfg_overrides.update(step.cfg)
    cfg_overrides["seed"] = args.seed
    cfg_overrides["step"] = step.name
    if args.max_tokens:
        cfg_overrides["max_tokens"] = args.max_tokens
    RUNS.mkdir(exist_ok=True)
    log = ProvenanceLog(RUNS / f"live-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}.jsonl")
    cfg = RunConfig(as_of=args.as_of, **cfg_overrides)
    sources = [s.strip() for s in args.search.split(",") if s.strip()]
    retractions = RetractionIndex.load(RW_DEFAULT) if RW_DEFAULT.exists() else None
    ctx = Context(client=client, judge_pool=pool, generator_families=[j.family for j in pool],
                  cfg=cfg, log=log, criteria=load_criteria(criteria_path), card_schema=load_card_schema(args.card),
                  search=build_search(sources), retractions=retractions)
    print(f"step: {step.name} ({step.description}){' [FAKE LLM]' if args.fake else ''}; criteria: {[c.name for c in ctx.criteria.criteria]} ({ctx.criteria.version}); "
          f"card: {ctx.card_schema.version}; search: {sources}{f', as of {args.as_of}' if args.as_of else ''}; "
          f"retraction check: {'on' if retractions else 'off (run: python -m hyparena.tools.retractions download)'}")
    print(f"families: {[j.family for j in pool]}  models: {[j.model_version for j in pool]}")
    print(f"log: {log.path}")
    return ctx, client


def smoke(args) -> None:
    ctx, client = _context(args)
    print(f"\n{'family':<18}{'model':<44}{'seconds':>8}{'json':>6}{'valid':>7}  note")
    for j in ctx.judge_pool:
        started = time.perf_counter()
        try:
            plan = PlanConfig(criteria=ctx.criteria.criteria)
            reply, _ = ctx.call(role="compare", family=j.family, template="compare", version="v3",
                                phase="rank", variables={"goal": GOAL, "plan": plan, "feedback": {},
                                                         "first": TOY[0], "second": TOY[1],
                                                         "example": verdict_example(plan.criteria),
                                                         "history_text": ""})
        except CallCapExceeded as e:
            print(f"stopped: {e}")
            break
        value = parse_json(reply.text)
        valid = bool(value) and all(value.get(c) in (1, 2) for c in plan.names)
        note = reply.error or (("picked " + "/".join(str(value.get(c)) for c in plan.names)) if valid
                               else reply.text[:50].replace("\n", " "))
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
    extra = {}
    if imported and dataset_options(args.import_file).get("dedup") is False:
        extra["dedup_threshold"] = 1.01          # off: templated items differ only in a name
        print("deduplication: off (requested by the dataset)")
    ctx, client = _context(args, **extra, max_cycles=args.cycles, gen_per_cycle=gen, evolve_per_cycle=1 if not imported else 0,
                           matches_per_item=args.matches)
    checkpointer = sqlite_checkpointer(args.checkpoint) if args.checkpoint else None
    graph = build_graph(ctx, checkpointer=checkpointer)
    thread = args.thread or f"run-{datetime.now():%Y%m%d-%H%M%S}"
    config = run_config(thread) if checkpointer else {"recursion_limit": 200}
    start = initial_state(goal, imported)
    if args.resume:
        if not (checkpointer and args.thread and has_checkpoint(graph, args.thread)):
            raise SystemExit("--resume needs --checkpoint and the --thread of an existing run")
        start = None
        print(f"resuming thread {thread}")
    elif checkpointer:
        print(f"checkpoints: {args.checkpoint}, thread {thread} (continue later with --resume --thread {thread})")
    try:
        final = graph.invoke(start, config=config)
    except CallCapExceeded as e:
        print(f"stopped: {e}; see the log for what was done"
              + (f"; continue with --resume --thread {thread}" if checkpointer else ""))
        return
    h = final["hypotheses"]
    if args.out:
        _dump(final, ctx, client, args.out)
    from collections import Counter
    print("\nstatus:", dict(Counter(x.status for x in h.values())))
    print("matches:", len(final["matches"]), " unparsable verdicts:",
          sum(1 for m in final["matches"] for v in m.judges if not v.parse_ok))
    viol = sum(1 for m in final["matches"] for v in m.judges
               if v.provenance.family in (h[m.a].provenance.family, h[m.b].provenance.family))
    print("judge independence violations:", viol)
    if final["report"].get("pending"):
        print("not evaluated (created after the last review or tournament):", final["report"]["pending"])
    print(f"calls: {client.calls}, failures: {client.failures}, by family: {client.by_family}")
    print(render(final["report"]["tokens"]))
    ratings, plan = final["ratings"], final["plan"]
    active = [i for i, x in h.items() if x.status == "active"]
    if ratings.get("promise") and active:
        score, _ = combined(ratings, plan.weights, active)
        print(f"\nranking (combined; {' / '.join(plan.names)}; games; evidence):")
        for i in sorted(range(len(active)), key=lambda k: -score[k]):
            hid = active[i]
            title = h[hid].text.split("\n", 1)[0][:60]
            per = " / ".join(f"{ratings[c][hid].score:5.2f}" for c in plan.names)
            print(f"  {hid:<8}{score[i]:>6.2f}  {per}  {ratings[plan.names[0]][hid].games:>2}  {len(h[hid].evidence):>2}"
                  f"  [{h[hid].provenance.family}] {title}")
    if final["report"].get("overview"):
        print("\nresearch overview:\n" + final["report"]["overview"][:1500])
    for s in final["report"]["shown"][:3]:
        scores = ", ".join(f"{c} {r['score']:.2f}" for c, r in s["ratings"].items())
        print(f"\n[{s['id']}] by {s['provenance']['family']} - {scores}\n{s['text'][:300]}")


def _dump(final, ctx, client, path) -> None:
    """Run result for evaluation outside the pipeline (hyparena.backtest evaluate)."""
    plan, ratings, hyps = final["plan"], final.get("ratings", {}), final["hypotheses"]
    rated = [i for i, x in hyps.items() if x.status == "active" and plan.names and i in ratings.get(plan.names[0], {})]
    score, _ = combined(ratings, plan.weights, rated) if rated else ([], [])
    comb = dict(zip(rated, [float(s) for s in score]))
    out = {"criteria": plan.names, "weights": plan.weights, "step": ctx.cfg.step,
           "seed": ctx.cfg.seed, "families": [j.family for j in ctx.judge_pool],
           "config": {k: getattr(ctx.cfg, k) for k in ("rating", "pairing", "judge_view", "lineage_mode",
                                                        "judges_per_match", "extra_judges", "max_tokens", "max_cycles")},
           "as_of": ctx.cfg.as_of, "matches": len(final.get("matches", [])), "calls": client.calls,
           "failures": client.failures, "tokens": ctx.tracer.summary(),
           "hypotheses": {i: {"status": x.status, "family": x.provenance.family, "combined": comb.get(i),
                              "scores": {c: ratings[c][i].model_dump() for c in plan.names if i in ratings.get(c, {})},
                              "evidence": len(x.evidence)} for i, x in hyps.items()}}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(out, indent=2))
    print(f"result written to {path}")


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
    parser.add_argument("--mode", choices=["full", "coscientist"], default="full",
                        help="full: our method; coscientist: baseline (one family, one Elo, holistic verdict)")
    parser.add_argument("--ladder", choices=sorted(LADDER), default=None,
                        help="ablation step L0 (baseline) .. L4 (full); overrides --mode (docs/comparison.md)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--fake", action="store_true", help="fake LLM, no model calls (tests the machinery)")
    parser.add_argument("--criteria", default=str(CONFIGS / "criteria.yaml"), help="criteria file (default: by step)")
    parser.add_argument("--card", default=str(CONFIGS / "card.yaml"), help="hypothesis card schema")
    parser.add_argument("--search", default="europepmc,pubtator,opengenes,clinicaltrials",
                        help=f"comma-separated sources from {', '.join(SOURCES)}, or none")
    parser.add_argument("--as-of", default=None, help="ISO date: evidence published on or before it only")
    parser.add_argument("--cycles", type=int, default=1, help="tournament cycles")
    parser.add_argument("--max-tokens", type=int, default=None, help="estimated token budget (stops at a cycle boundary)")
    parser.add_argument("--out", default=None, help="write the run result as JSON (for hyparena.backtest evaluate)")
    parser.add_argument("--checkpoint", default=None, help="SQLite file for the graph state, e.g. runs/state.sqlite")
    parser.add_argument("--thread", default=None, help="run id inside the checkpoint file")
    parser.add_argument("--resume", action="store_true", help="continue the --thread run from its last checkpoint")
    args = parser.parse_args()
    args.criteria_given = "--criteria" in sys.argv
    {"smoke": smoke, "run": run}[args.command](args)


if __name__ == "__main__":
    main()
