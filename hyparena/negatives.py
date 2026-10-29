"""Negative-sampling test: does the ranking put a confirmed finding above plausible false ones?

    python -m hyparena.negatives build --groups 6 --config configs/paid-test.yaml --writer zhipu --verifier google
    python -m hyparena.negatives run --steps L0,L4 --seeds 0                 # prints commands; --execute runs them
    python -m hyparena.negatives listwise --families openai,google          # one-call baseline per group
    python -m hyparena.negatives evaluate --runs runs/neg/L4_s0
    python -m hyparena.negatives compare --a runs/neg/L4_s0 --b runs/neg/L0_s0

A group is one confirmed finding and nine negatives (docs/negative-sampling.md):
- the finding: a compound that significantly increased average lifespan of a species in at least two
  DrugAge publications, and never significantly decreased it;
- real negatives: compounds tested in the same species that never had a significant effect (DrugAge);
- synthetic variants of the finding (reversed effect, wrong condition, failed analogue, wrong mechanism),
  written by the writer model and kept only if a verifier of another family calls them false;
- a decoy: one real negative with as many synthetic variants (reversed effect, a mechanism for an effect it
  does not have; false by the data). Without it the finding would be the only compound named several times
  in the group, which gives the answer away.
All ten statements are then rewritten by the writer in one call, in one format and in random order, without
being told which is true, so that style does not give the answer away either. Each group is ranked by its
own tournament, with evidence cut off the day before the finding was first published (`as_of`).

Labels and the kinds of the negatives go to labels.json, which the pipeline never reads. Metrics: hit@1
(the finding is ranked first), MRR, mean rank, AUC within the group (share of negatives ranked below the
finding), and the same share per kind of negative. Chance level for ten items: hit@1 0.10, MRR 0.29, AUC 0.5."""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import random
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from hyparena.backtest import _pubdates, _scores, drugage_rows
from hyparena.data import load_imported
from hyparena.experiment import execute
from hyparena.llm.fake import FakeLLMClient
from hyparena.llm.judges import JudgeSpec
from hyparena.llm.prompts import render
from hyparena.llm.providers import DEFAULT_CONFIG, GuardedClient, build_client, load_config
from hyparena.llm.structured import parse_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "negatives"
RUNS = ROOT / "runs" / "neg"
GOAL = "Identify the most promising and feasible hypotheses on interventions that extend lifespan."

KINDS = {
    "reversed": "the same intervention and organism with the opposite effect (shortens lifespan or accelerates ageing).",
    "condition": "the same intervention and organism, restricted to a condition (sex, life stage, genetic background, "
                 "diet, dose) in which the effect is known to be absent.",
    "analog": "a related intervention (same class or target) that was tested in this organism and did not extend "
              "lifespan, claimed to extend it.",
    "mechanism": "the same effect attributed to a mechanism or requirement that published work rules out.",
}
#: Variants of the decoy (a compound without a significant effect): false by the data, no verifier needed.
DECOY_KINDS = {
    "reversed": "the same intervention and organism with the opposite effect (shortens lifespan or accelerates ageing).",
    "mechanism": "the same claimed lifespan extension, attributed to a specific, plausible mechanism.",
}
STATUS = {"finding": "a published, replicated finding",
          "unsupported": "a claim that was tested in this organism and had no significant effect on lifespan"}


def _pct(v: str) -> float:
    try:
        return float(v)
    except ValueError:
        return 0.0


def _statement(compound: str, species: str) -> str:
    return f"{compound} extends lifespan in {species}."


def _key(*parts) -> str:
    return hashlib.sha1(":".join(map(str, parts)).encode()).hexdigest()


def select(rows: list[dict], n_groups: int, size: int, min_pubs: int = 2, seed: int = 0,
           exclude: frozenset = frozenset()) -> list[dict]:
    """Confirmed findings and real negatives from DrugAge rows, round-robin over species so that one model
    organism does not fill the test. `exclude`: (compound, species) findings already used (groups the rules were
    fixed on), never chosen again."""
    stats = defaultdict(lambda: {"pos": set(), "ns": set(), "sig_neg": False, "sig": False})
    for r in rows:
        st = stats[(r["compound_name"].strip(), r["species"].strip())]
        sig, pmid = r["avg_lifespan_significance"].strip(), r["pubmed_id"].strip()
        if sig == "S":
            st["sig"] = True
            if _pct(r["avg_lifespan_change_percent"]) > 0 and pmid:
                st["pos"].add(pmid)
            elif _pct(r["avg_lifespan_change_percent"]) < 0:
                st["sig_neg"] = True
        elif sig == "NS" and pmid:
            st["ns"].add(pmid)
    negatives = defaultdict(list)
    for (compound, species), st in stats.items():
        if not st["sig"] and st["ns"]:
            negatives[species].append({"compound": compound, "pmids": sorted(st["ns"])})
    positives = defaultdict(list)
    for (compound, species), st in stats.items():
        if len(st["pos"]) >= min_pubs and not st["sig_neg"] and len(negatives[species]) >= size \
                and (compound, species) not in exclude:
            positives[species].append({"compound": compound, "species": species, "pmids": sorted(st["pos"])})
    for species in positives:
        positives[species].sort(key=lambda p: _key(seed, p["compound"], species))
    order = sorted(positives, key=lambda s: -len(positives[s]))
    groups, i = [], 0
    while len(groups) < n_groups and any(positives.values()):
        species = order[i % len(order)]
        i += 1
        if positives[species]:
            pos = positives[species].pop(0)
            pool = sorted(negatives[species], key=lambda n: _key(seed, pos["compound"], n["compound"]))
            groups.append({"positive": pos, "real": [n for n in pool if n["compound"] != pos["compound"]]})
    return groups


def _client(args):
    if args.fake:
        specs = [s for s in load_config(args.config).models if s.enabled]
        return GuardedClient(FakeLLMClient(args.seed), rpm=0, max_calls=args.max_calls), \
            [JudgeSpec(s.family, f"fake-{s.model}") for s in specs]
    client, pool, _ = build_client(args.config, max_calls=args.max_calls)
    return client, pool


def synthesize(client, statement: str, status: str, kinds: dict[str, str], n: int, writer: str,
               verifier: str | None, min_confidence: float) -> dict:
    """Up to `n` false variants of `statement`, generated by the writer (two candidates per kind) and, with a
    `verifier`, kept only if it calls them false with enough confidence. Kinds are taken in turn."""
    order = [k for _ in range(2) for k in kinds]
    reply = client.call(role="negatives_generate", family=writer, prompt=render(
        "negatives_generate", "v1", statement=statement, status=STATUS[status], n=len(order), kinds=order,
        kind_descriptions=kinds))
    made = [s for s in ((parse_json(reply.text) or {}).get("statements") or [])
            if isinstance(s, dict) and s.get("statement") and s.get("kind") in kinds]
    if not made:
        return {"kept": [], "dropped": [], "error": reply.error or "unparsable generation"}
    if verifier:
        check = client.call(role="negatives_verify", family=verifier, avoid=frozenset({writer}),
                            prompt=render("negatives_verify", "v1", statements=[s["statement"] for s in made]))
        verdicts = {int(v.get("n", 0)): v for v in ((parse_json(check.text) or {}).get("verdicts") or [])
                    if isinstance(v, dict) and str(v.get("n", "")).isdigit()}
        checked = [{**s, "verdict": verdicts.get(i, {}).get("verdict"), "confidence": verdicts.get(i, {}).get("confidence"),
                    "verifier": check.family} for i, s in enumerate(made, start=1)]
        ok = lambda s: s["verdict"] == "false" and float(s["confidence"] or 0) >= min_confidence
    else:
        checked = [{**s, "verdict": "false", "confidence": None, "verifier": "data"} for s in made]
        ok = lambda s: True
    by_kind = defaultdict(list)
    for s in checked:
        if ok(s):
            by_kind[s["kind"]].append(s)
    chosen = []
    while len(chosen) < n and any(by_kind.values()):
        for k in kinds:
            if by_kind[k] and len(chosen) < n:
                chosen.append(by_kind[k].pop(0))
    return {"kept": chosen, "dropped": [s for s in checked if s not in chosen], "error": ""}


def build(args) -> None:
    client, pool = _client(args)
    families = [j.family for j in pool]
    for role, fam in (("writer", args.writer), ("verifier", args.verifier)):
        if fam not in families:
            raise SystemExit(f"--{role} {fam} is not an enabled family in {args.config}: {families}")
    if args.writer == args.verifier:
        raise SystemExit("the verifier must be from another family than the writer")
    used = frozenset((x["compound"], g["species"]) for f in args.exclude_from
                     for g in json.loads(Path(f).read_text()).values() for x in g["items"].values() if x["label"] == 1)
    groups = select(drugage_rows(), args.groups, args.size, args.min_pubs, args.seed, used)
    dates = _pubdates(sorted({p for g in groups for p in g["positive"]["pmids"]}))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    labels, report = {}, []
    for gi, g in enumerate(groups, start=1):
        gid = f"g{gi:03d}"
        pos, decoy = g["positive"], g["real"][0]
        first = min((dates[p] for p in pos["pmids"] if p in dates), default=None)
        if not first:
            report.append(f"{gid} skipped: no publication date for {pos['compound']}")
            continue
        as_of = (date.fromisoformat(first) - timedelta(days=1)).isoformat()
        species = pos["species"]
        true_syn = synthesize(client, _statement(pos["compound"], species), "finding", KINDS, args.variants,
                              args.writer, args.verifier, args.min_confidence)
        decoy_syn = synthesize(client, _statement(decoy["compound"], species), "unsupported", DECOY_KINDS,
                               len(true_syn["kept"]), args.writer, None, args.min_confidence)
        k = min(len(true_syn["kept"]), len(decoy_syn["kept"]))      # clusters of the same size
        n_real = args.size - 1 - 2 * k                                  # the decoy itself is the first real one
        items = [{"kind": "true", "label": 1, "statement": _statement(pos["compound"], species),
                  "compound": pos["compound"], "pmids": pos["pmids"]}]
        items += [{"kind": "real", "label": 0, "statement": _statement(n["compound"], species), "decoy": i == 0,
                   "compound": n["compound"], "pmids": n["pmids"]} for i, n in enumerate(g["real"][:n_real])]
        items += [{"kind": s["kind"], "label": 0, "statement": s["statement"], "why_false": s.get("why_false", ""),
                   "verifier": s["verifier"], "confidence": s["confidence"]} for s in true_syn["kept"][:k]]
        items += [{"kind": f"decoy_{s['kind']}", "label": 0, "statement": s["statement"], "why_false": s.get("why_false", ""),
                   "verifier": "data", "confidence": None} for s in decoy_syn["kept"][:k]]
        random.Random(_key(args.seed, gid)).shuffle(items)
        reply = client.call(role="negatives_rewrite", family=args.writer,
                            prompt=render("negatives_rewrite", "v1", statements=[x["statement"] for x in items]))
        rewritten = {int(h.get("n", 0)): h for h in ((parse_json(reply.text) or {}).get("hypotheses") or [])
                     if isinstance(h, dict)}
        if len(rewritten) < len(items) or not all(rewritten.get(n, {}).get("claim") for n in range(1, len(items) + 1)):
            report.append(f"{gid} skipped: rewrite returned {len(rewritten)} of {len(items)} ({reply.error[:80]})")
            continue
        hyps = [{"id": n, **{k: rewritten[n].get(k, "") for k in ("title", "claim", "rationale", "prediction", "experiment")}}
                for n in range(1, len(items) + 1)]
        (out / f"{gid}.json").write_text(json.dumps({
            "source": {"family": reply.family, "model": reply.model_id, "strategy": "negative-sampling",
                       "as_of": as_of, "note": "labels are in labels.json",
                       "options": {"dedup": False, "lang": "en"}},
            "hypotheses": hyps, "assistant_notes": {}}, ensure_ascii=False, indent=2))
        labels[gid] = {"as_of": as_of, "species": pos["species"], "writer": reply.family,
                       "items": {f"imp{n:03d}": x for n, x in enumerate(items, start=1)},
                       "dropped_synthetic": true_syn["dropped"] + decoy_syn["dropped"]}
        kinds = defaultdict(int)
        for x in items:
            kinds[x["kind"]] += 1
        report.append(f"{gid} {pos['compound']} / {pos['species']} as of {as_of}: {dict(kinds)}; "
                      f"variants per cluster: {k}; candidates not used: {len(true_syn['dropped'])} (rejected by the verifier or surplus)")
    (out / "labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=2))
    rel = lambda v: str(Path(v).resolve().relative_to(ROOT)) if isinstance(v, str) and Path(v).is_absolute() \
        and Path(v).resolve().is_relative_to(ROOT) else v     # no local paths in the committed record
    (out / "build.json").write_text(json.dumps({"args": {k: rel(v) for k, v in vars(args).items() if k != "func"},
                                                "calls": client.calls, "report": report}, indent=2))
    print("\n".join(report))
    print(f"groups written: {len(labels)} of {len(groups)}; calls: {client.calls} (failures: {client.failures}; "
          f"by family: {client.by_family}); {out}")


def _groups(data_dir: Path) -> tuple[dict, list[str]]:
    labels = json.loads((data_dir / "labels.json").read_text())
    return labels, sorted(labels)


def run(args) -> None:
    labels, gids = _groups(Path(args.data))
    runs = []
    for step in args.steps.split(","):
        for seed in args.seeds.split(","):
            for gid in gids:
                path = Path(args.out_dir) / f"{step}_s{seed}" / f"{gid}.json"
                cmd = [sys.executable, "-m", "hyparena.live", "run", "--import-file", str(Path(args.data) / f"{gid}.json"),
                       "--ladder", step, "--seed", seed, "--as-of", labels[gid]["as_of"], "--goal", GOAL,
                       "--cycles", str(args.cycles), "--matches", str(args.matches), "--max-calls", str(args.max_calls),
                       "--config", args.config, "--search", args.search, "--out", str(path)]
                if args.max_tokens:
                    cmd += ["--max-tokens", str(args.max_tokens)]
                if args.fake:
                    cmd.append("--fake")
                runs.append((path, cmd))
    execute(runs, args.execute, Path(args.out_dir) / "manifest.json")


def run_v2(args) -> None:
    """Our method v2 (verified cards, rules, aggregation) on every group, evidence as of the group's date;
    results in the format `evaluate` reads, plus the full v2 output next to each."""
    from hyparena.card.pipeline import as_ladder_result
    from hyparena.card.pipeline import run as v2
    labels, gids = _groups(Path(args.data))
    out = Path(args.out_dir) / (f"v2-{args.profile}" + (f"-{args.tag}" if args.tag else ""))
    out.mkdir(parents=True, exist_ok=True)
    for gid in gids:
        path = out / f"{gid}.json"
        if path.exists():
            continue
        hyps = load_imported(Path(args.data) / f"{gid}.json")
        saved = Path(args.cards_from) / f"{gid}.v2.json" if args.cards_from else None
        cards = None
        if saved and saved.exists():
            earlier = json.loads(saved.read_text())
            if not any("quota" in (c.get("error") or "") for c in earlier["calls"]):   # a run cut by the balance has no cards
                cards = [x["card"] for x in earlier["items"]]
        res = v2([h.text for h in hyps], writer=labels[gid]["writer"], config=args.config, fake=args.fake,
                 as_of=labels[gid]["as_of"], max_calls=args.max_calls, K=args.K,
                 verifiers=args.verifiers.split(",") if args.verifiers else None, cards=cards)
        (out / f"{gid}.v2.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
        path.write_text(json.dumps(as_ladder_result(res, [h.id for h in hyps], args.profile), indent=2))
        print(f"{gid}: {res['meta']['calls']} calls, {res['meta']['seconds']} s")
    print(out)


def refresh_v2(args) -> None:
    """Recompute saved v2 results with the current curated sources and rules (no model calls)."""
    from hyparena.card.pipeline import as_ladder_result, refresh_curated
    labels, gids = _groups(Path(args.data))
    src = Path(args.out_dir) / (f"v2-{args.profile}" + (f"-{args.tag}" if args.tag else ""))
    dst = Path(src.parent) / f"{src.name}-{args.suffix}"
    dst.mkdir(parents=True, exist_ok=True)
    for gid in gids:
        f = src / f"{gid}.v2.json"
        if not f.exists():
            continue
        res = refresh_curated(json.loads(f.read_text()), K=args.K)
        hyps = load_imported(Path(args.data) / f"{gid}.json")
        (dst / f"{gid}.v2.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
        (dst / f"{gid}.json").write_text(json.dumps(as_ladder_result(res, [h.id for h in hyps], args.profile), indent=2))
    print(dst)


def listwise(args) -> None:
    """Baseline: one call per group and family that ranks all ten hypotheses at once (no tournament)."""
    labels, gids = _groups(Path(args.data))
    client, pool = _client(args)
    families = args.families.split(",") if args.families else [j.family for j in pool]
    for fam in families:
        out = Path(args.out_dir) / (f"list-{fam}" + (f"-{args.tag}" if args.tag else ""))
        out.mkdir(parents=True, exist_ok=True)
        for gid in gids:
            if fam == labels[gid]["writer"]:
                print(f"skip {gid} for {fam}: the writer's family does not judge its own hypotheses")
                continue
            hyps = load_imported(Path(args.data) / f"{gid}.json")
            prompt = render("listwise", "v1", goal=GOAL, hypotheses=hyps,
                            example_ids=", ".join(f'"{h.id}"' for h in hyps[:2]) + ", ...")
            reply = client.call(role="listwise", family=fam, prompt=prompt, avoid=frozenset({labels[gid]["writer"]}))
            order = [h for h in dict.fromkeys((parse_json(reply.text) or {}).get("ranking") or [])
                     if h in {x.id for x in hyps}]
            result = {"criteria": [], "step": f"list-{fam}", "families": [reply.family], "calls": 1,
                      "tokens": {"rank": {"tokens_in": reply.tokens_in, "tokens_out": reply.tokens_out}},
                      "error": reply.error,
                      "hypotheses": {h.id: {"status": "active",
                                            "combined": float(len(order) - order.index(h.id)) if h.id in order else None}
                                     for h in hyps}}
            (out / f"{gid}.json").write_text(json.dumps(result, indent=2))
        print(f"{fam}: {out}")
    print(f"calls: {client.calls}")


def _group_metrics(group: dict, result: dict, key: str) -> dict | None:
    items = group["items"]
    s = _scores(result, key, items, "bottom")
    true = next(h for h, x in items.items() if x["label"] == 1)
    if true not in s:
        return None
    t = s[true]
    negs = [h for h in items if h != true]
    above = sum(s[h] > t for h in negs)
    ties = sum(s[h] == t for h in negs)
    rank = 1 + above + 0.5 * ties
    by_kind = defaultdict(list)
    for h in negs:
        by_kind[items[h]["kind"]].append((t > s[h]) + 0.5 * (t == s[h]))
    return {"hit1": float(above == 0 and ties == 0), "rr": 1 / rank, "rank": rank,
            "auc": sum((t > s[h]) + 0.5 * (t == s[h]) for h in negs) / len(negs),
            "true_status": result["hypotheses"].get(true, {}).get("status", "missing"),
            "by_kind": {k: sum(v) / len(v) for k, v in by_kind.items()}}


def _mean(v):
    return sum(v) / len(v) if v else float("nan")


def _ci(values: list[float], n_boot: int = 2000, seed: int = 0) -> list[float]:
    rng = random.Random(seed)
    boots = sorted(_mean([rng.choice(values) for _ in values]) for _ in range(n_boot))
    return [boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1]]


def _per_group(labels: dict, run_dirs: list[str], key: str) -> dict[str, list[dict]]:
    """Group id -> metrics of each run directory (seed) that has a result for it."""
    out = defaultdict(list)
    for d in run_dirs:
        for gid, group in labels.items():
            path = Path(d) / f"{gid}.json"
            if path.exists():
                m = _group_metrics(group, json.loads(path.read_text()), key)
                if m:
                    out[gid].append(m)
    return out


def evaluate(data: str, run_dirs: list[str], key: str = "combined") -> dict:
    labels = json.loads((Path(data) / "labels.json").read_text())
    per = _per_group(labels, run_dirs, key)
    rows = [m for ms in per.values() for m in ms]
    out = {"key": key, "groups": len(per), "runs": len(rows)}
    if not rows:
        return out
    for name in ("hit1", "rr", "rank", "auc"):
        vals = [_mean([m[name] for m in ms]) for ms in per.values()]
        out[name] = {"mean": _mean(vals), "ci95": _ci(vals)}
    kinds = defaultdict(list)
    for m in rows:
        for k, v in m["by_kind"].items():
            kinds[k].append(v)
    out["true_ranked_above_kind"] = {k: round(_mean(v), 3) for k, v in sorted(kinds.items())}
    status = defaultdict(int)
    for m in rows:
        status[m["true_status"]] += 1
    out["true_status"] = dict(status)
    out["chance"] = {"hit1": 0.1, "rr": 0.293, "rank": 5.5, "auc": 0.5}
    tokens = [sum(r["tokens_in"] + r["tokens_out"] for r in json.loads((Path(d) / f"{g}.json").read_text())
                  .get("tokens", {}).values()) for d in run_dirs for g in labels if (Path(d) / f"{g}.json").exists()]
    out["mean_estimated_tokens_per_group"] = _mean(tokens)
    return out


def compare(data: str, a_dirs: list[str], b_dirs: list[str], key: str = "combined", n_boot: int = 2000) -> dict:
    """Paired comparison over groups (seeds averaged per group) of MRR and AUC: A - B with a bootstrap CI."""
    labels = json.loads((Path(data) / "labels.json").read_text())
    pa, pb = _per_group(labels, a_dirs, key), _per_group(labels, b_dirs, key)
    common = sorted(set(pa) & set(pb))
    out = {"key": key, "groups": len(common)}
    rng = random.Random(0)
    for name in ("hit1", "rr", "auc"):
        diffs = [_mean([m[name] for m in pa[g]]) - _mean([m[name] for m in pb[g]]) for g in common]
        if not diffs:
            continue
        boots = [_mean([rng.choice(diffs) for _ in diffs]) for _ in range(n_boot)]
        out[name] = {"A": _mean([_mean([m[name] for m in pa[g]]) for g in common]),
                     "B": _mean([_mean([m[name] for m in pb[g]]) for g in common]),
                     "A_minus_B": _mean(diffs), "ci95": [sorted(boots)[int(0.025 * n_boot)], sorted(boots)[int(0.975 * n_boot) - 1]],
                     "share_of_bootstrap_above_0": sum(b > 0 for b in boots) / n_boot}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    llm = argparse.ArgumentParser(add_help=False)
    llm.add_argument("--config", default=str(DEFAULT_CONFIG))
    llm.add_argument("--max-calls", type=int, default=200)
    llm.add_argument("--seed", type=int, default=0)
    llm.add_argument("--fake", action="store_true", help="fake LLM, no model calls")
    data = argparse.ArgumentParser(add_help=False)
    data.add_argument("--data", default=str(DATA / "drugage"))
    b = sub.add_parser("build", parents=[llm])
    b.add_argument("--groups", type=int, default=6)
    b.add_argument("--size", type=int, default=10, help="hypotheses per group (one is the finding)")
    b.add_argument("--variants", type=int, default=2, help="synthetic variants of the finding and of the decoy each "
                                                           "(real negatives fill the rest of the group)")
    b.add_argument("--min-pubs", type=int, default=2, help="publications with a significant increase for a finding")
    b.add_argument("--min-confidence", type=float, default=0.7, help="verifier confidence to keep a synthetic negative")
    b.add_argument("--writer", required=True, help="family that writes all hypotheses of a group")
    b.add_argument("--verifier", required=True, help="family that checks synthetic negatives (not the writer)")
    b.add_argument("--out", default=str(DATA / "drugage"))
    b.add_argument("--exclude-from", nargs="*", default=[], help="labels.json of earlier builds: their findings are not chosen again")
    r = sub.add_parser("run", parents=[data])
    r.add_argument("--steps", default="L0,L4")
    r.add_argument("--seeds", default="0")
    r.add_argument("--cycles", type=int, default=4)
    r.add_argument("--matches", type=float, default=3.0, help="matches per hypothesis per cycle")
    r.add_argument("--max-tokens", type=int, default=None, help="estimated token budget per group")
    r.add_argument("--max-calls", type=int, default=300)
    r.add_argument("--config", default="configs/paid-test.yaml")
    r.add_argument("--search", default="europepmc")
    r.add_argument("--out-dir", default=str(RUNS))
    r.add_argument("--fake", action="store_true")
    r.add_argument("--execute", action="store_true", help="run the commands (default: print them)")
    lw = sub.add_parser("listwise", parents=[llm, data])
    lw.add_argument("--families", default=None)
    lw.add_argument("--tag", default="", help="suffix of the output directory (a repeat)")
    lw.add_argument("--out-dir", default=str(RUNS))
    v = sub.add_parser("v2", parents=[data], help="our method v2 on every group")
    v.add_argument("--config", default="configs/v2.yaml")
    v.add_argument("--profile", default="evidence_first")
    v.add_argument("--max-calls", type=int, default=200)
    v.add_argument("--K", type=int, default=10000)
    v.add_argument("--out-dir", default=str(RUNS))
    v.add_argument("--fake", action="store_true")
    v.add_argument("--verifiers", default=None, help="comma-separated families that verify (default: all)")
    v.add_argument("--cards-from", default=None, help="directory of an earlier v2 run whose cards are reused")
    v.add_argument("--tag", default="", help="suffix of the output directory")
    rf = sub.add_parser("v2-refresh", parents=[data], help="recompute saved v2 results without model calls")
    rf.add_argument("--profile", default="evidence_first")
    rf.add_argument("--suffix", default="refreshed")
    rf.add_argument("--tag", default="", help="suffix of the source directory")
    rf.add_argument("--K", type=int, default=10000)
    rf.add_argument("--out-dir", default=str(RUNS))
    e = sub.add_parser("evaluate", parents=[data])
    e.add_argument("--runs", nargs="+", required=True, help="run directories (one per seed; globs allowed)")
    e.add_argument("--key", default="combined", help="combined or a criterion name")
    c = sub.add_parser("compare", parents=[data])
    c.add_argument("--a", nargs="+", required=True)
    c.add_argument("--b", nargs="+", required=True)
    c.add_argument("--key", default="combined")
    args = ap.parse_args()
    expand = lambda ps: sorted(f for p in ps for f in (glob.glob(p) or [p]))
    if args.cmd == "build":
        build(args)
    elif args.cmd == "run":
        run(args)
    elif args.cmd == "listwise":
        listwise(args)
    elif args.cmd == "v2":
        run_v2(args)
    elif args.cmd == "v2-refresh":
        refresh_v2(args)
    elif args.cmd == "evaluate":
        print(json.dumps(evaluate(args.data, expand(args.runs), args.key), indent=2))
    else:
        print(json.dumps(compare(args.data, expand(args.a), expand(args.b), args.key), indent=2))


if __name__ == "__main__":
    main()
