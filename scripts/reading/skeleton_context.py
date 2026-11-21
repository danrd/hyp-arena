"""Offline replay of contextual reader decisions against frozen paper skeletons (packs 16/25)."""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

from scripts.reading.bench_reading import KG, _measures, _norm


def load_rows(kg):
    rows = defaultdict(list)
    paths = [kg / "reviews/codex-2026-11-09-skeleton/stage0_parses_2026-11-15.jsonl",
             *sorted((kg / "reviews/argon-2026-11-16").glob("skeleton_parses_*.jsonl"))]
    for path in paths:
        with path.open(encoding="utf-8") as source:
            for line in source:
                item = json.loads(line)
                skeleton = item["skeleton"]
                paper = skeleton["paper"]
                if paper.get("retracted"):
                    continue
                text = _norm(item["text"])
                for row in skeleton["results"] + skeleton["mechanistic_findings"]:
                    quote = _norm(row["quote"])
                    if row.get("quote_role") == "finding" and quote and quote in text:
                        rows[str(paper["pmid"])].append((quote, row["id"], path.name, paper.get("pub_date")))
    return rows


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def attach(reader_quote, abstract, candidates, as_of):
    quote = _norm(reader_quote)
    if not quote or quote not in abstract:
        return []
    matches = []
    for finding, row_id, source, date in candidates:
        if date and as_of and date[:10] > as_of[:10]:
            continue
        if min(len(finding.split()), len(quote.split())) >= 6 and (finding in quote or quote in finding):
            matches.append((source, row_id))
    return matches


def evaluate(kg, number, skeletons):
    folder = kg / "reviews" / {16: "argon-2026-11-12", 25: "argon-2026-11-15"}[number]
    pack = f"pack_{number}"
    tasks = {item["id"]: item for part in "ab" for item in read(folder / f"{pack}{part}_task.json")["items"]}
    answers = [folder / f"{pack}_answer.json"] if number == 16 else [folder / f"{pack}{p}_answer.json" for p in "ab"]
    gold = {(item["id"], str(paper["pmid"])): paper for path in answers for item in read(path)["items"]
            for paper in item["papers"]}
    output, audit = {}, []
    for suffix in ("", "_2"):
        skeleton = read(folder / f"bench_reading_skel{suffix}.json")
        reader = read(folder / f"bench_reading_v21{suffix}.json")
        systems = defaultdict(list)
        for rid, task in tasks.items():
            for paper in task["papers"]:
                pmid = str(paper["pmid"])
                abstract = _norm(paper["title"] + " " + paper["abstract"])
                old = skeleton[rid]["records"].get(pmid)
                contextual = reader[rid]["records"].get(pmid)
                matches = attach(contextual[1], abstract, skeletons.get(pmid, []), task["T"]) if contextual else []
                attached = contextual if matches else None
                unique = contextual if len(matches) == 1 else None
                for name, record in (("skeleton", old), ("reader", contextual), ("attached", attached),
                                     ("unique", unique),
                                     ("rescue", old or attached)):
                    label = gold[rid, pmid]
                    systems[name].append(dict(rid=rid, gold=label["finding"], sys=record[0] if record else "none",
                                              none_reason=label.get("none_reason"), verbatim=bool(record and record[1])
                                              and _norm(record[1]) in abstract))
                if matches:
                    audit.append(dict(run=suffix or "1", rid=rid, pmid=pmid, row_candidates=matches,
                                      reader_side=contextual[0], skeleton_side=old[0] if old else None))
        if len(systems["reader"]) != len(gold):
            raise ValueError("task and reference pairs differ")
        metrics = {name: _measures(rows) for name, rows in systems.items()}
        by_link = defaultdict(list)
        for original, rescued in zip(systems["skeleton"], systems["rescue"], strict=True):
            positive = original["gold"] in ("for", "against")
            by_link[original["rid"]].append((positive, int(positive and rescued["sys"] == original["gold"])
                                             - int(positive and original["sys"] == original["gold"])))
        rng = random.Random(16)
        deltas = []
        for _ in range(2000):
            sample = [row for link in rng.choices(list(by_link), k=len(by_link)) for row in by_link[link]]
            positives = sum(row[0] for row in sample)
            if positives:
                deltas.append(sum(row[1] for row in sample) / positives)
        deltas.sort()
        metrics["paired_delta_recall_ci95"] = [deltas[int(q * (len(deltas) - 1))] for q in (0.025, 0.975)]
        output[suffix or "1"] = metrics
    return output, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kg", type=Path, default=KG)
    parser.add_argument("--out", type=Path, default=Path("runs/skeleton-context"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rows = load_rows(args.kg)
    summary = {}
    for number in (16, 25):
        summary[number], audit = evaluate(args.kg, number, rows)
        (args.out / f"row-candidates-{number}.json").write_text(json.dumps(audit), encoding="utf-8")
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for number, repeats in summary.items():
        for repeat, metrics in repeats.items():
            print(number, repeat, {key: (round(value["recall"], 3), round(value["precision"], 3))
                                    for key, value in metrics.items() if isinstance(value, dict)},
                  metrics["paired_delta_recall_ci95"])


if __name__ == "__main__":
    main()
