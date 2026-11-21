"""Controlled pilot of adjudicate_v4 with/without frozen paper context, without reparsing papers.

Run from hyp-arena with KG_DIR set to the sibling longevity-kg checkout.
Default prepares both arms offline. --live invokes the original configured DeepSeek judge.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=2, help="Links per pack, in stable hash order")
    parser.add_argument("--out", type=Path, default=Path("runs/skeleton-judge-ab"))
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    kg = Path(os.environ.get("KG_DIR", Path(__file__).resolve().parents[3] / "longevity-kg")).resolve()
    os.environ["KG_DIR"] = str(kg)
    sys.path.insert(0, str(kg))
    from tools.skeleton import bench, session, store
    from scripts.reading import bench_reading as scoring
    from scripts.whole_system.codex_benchmark import write_json

    if session.ADJUDICATE_VERSION != "adjudicate_v4":
        parser.error("the frozen pilot requires adjudicate_v4")
    client = session.paid_client(max_calls=200) if args.live else None
    args.out.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="skeleton-db-", dir=args.out) as scratch:
        run(Path(scratch) / "frozen.db", args, client, bench, session, store, scoring, write_json)


def run(db, args, client, bench, session, store, scoring, write_json):
    paths = [bench.OLD_PARSES, *sorted(bench.OUT.glob("skeleton_parses_*.jsonl"))]
    inputs = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    with closing(store.connect(db)) as conn:
        store.create_tables(conn)
        for path in paths:
            store.load_jsonl(conn, path)
        snapshots = {eid: (sk, text) for eid, sk, text in store.readings(conn)}
    source_text = {eid[:16]: scoring._norm(text) for eid, (_, text) in snapshots.items()}
    if len(source_text) != len(snapshots):
        raise RuntimeError("duplicate extraction ID prefixes")
    report = {"judge": session.ADJUDICATE_VERSION, "inputs": inputs, "packs": {}}
    for pack in ("16", "25"):
        scoring.PACK, scoring.DIR = f"pack_{pack}", bench.PACKS[pack]
        targets = sorted(bench.targets(pack), key=lambda t: hashlib.sha256(t["rid"].encode()).digest())[:args.limit]
        outputs = {}
        prompt_ids = {}
        counts = {"links": len(targets), "rows": 0, "batches_per_arm": 0}
        for target in targets:
            rid, claim = target["rid"], target["claim"]
            papers = [str(p["pmid"]) for p in target["task"]["papers"]]
            _, candidates = session.candidates(db, claim, papers, target["as_of"])
            counts["rows"] += len(candidates)
            counts["batches_per_arm"] += (len(candidates) + session.ADJ_BATCH - 1) // session.ADJ_BATCH
            for arm in ("row", "context"):
                batch = []
                for candidate in candidates:
                    item = candidate["item"].copy()
                    if arm == "context":
                        sk, text = snapshots[candidate["extraction_id"]]
                        row = next(row for row in sk.results + sk.mechanistic_findings if row.id == candidate["row_id"])
                        item.update(paper_context=text.split("\n\nResults and tables:", 1)[0],
                                    time_point=getattr(row, "time_point", None), location=row.location)
                    batch.append({**candidate, "item": item})
                prompts = [session.adjudicate_prompt(claim, [dict(id=c["id"], **c["item"]) for c in
                           batch[start:start + session.ADJ_BATCH]]) for start in range(0, len(batch), session.ADJ_BATCH)]
                fingerprint = hashlib.sha256(json.dumps(prompts).encode()).hexdigest()
                prompt_ids.setdefault(rid, {})[arm] = fingerprint
                path = args.out / f"{pack}-{rid}-{arm}-{fingerprint[:16]}.json"
                counts[arm + "_chars"] = counts.get(arm + "_chars", 0) + sum(map(len, prompts))
                if client is None:
                    continue
                cached = path.exists()
                if cached:
                    answers = json.loads(path.read_text(encoding="utf-8"))["answers"]
                else:
                    log = []
                    answers = session.adjudicate(client, claim, batch, log)
                if answers.keys() != {c["id"] for c in batch}:
                    raise RuntimeError(f"incomplete judge answers for pack {pack}, link {rid}, arm {arm}")
                if not cached:
                    write_json(path, {"answers": answers, "calls": log, "prompt_sha256": fingerprint})
                verification, _ = session.verification(db, claim, papers, target["as_of"], answers=answers)
                records = {}
                for side, group in (("for", verification.evidence), ("against", verification.counterevidence)):
                    for record in group:
                        pmid = str(record.linked_pmid or record.record_id).replace("PMID:", "")
                        _, extraction, _ = record.record_id.split("/", 2)
                        quote = scoring._norm(record.quote)
                        records.setdefault(pmid, []).append({"side": side, "record_id": record.record_id,
                                                            "verbatim": bool(quote) and quote in source_text[extraction]})
                outputs.setdefault(arm, {})[rid] = records
        print(pack, counts, flush=True)
        pack_report = {"counts": counts, "prompts": prompt_ids}
        report["packs"][pack] = pack_report
        if outputs:
            gold_files = ["pack_16_answer.json"] if pack == "16" else ["pack_25a_answer.json", "pack_25b_answer.json"]
            gold = {item["id"]: item["papers"] for filename in gold_files for item in
                    json.loads((scoring.DIR / filename).read_text(encoding="utf-8"))["items"]}
            for arm, links in outputs.items():
                rows = []
                for target in targets:
                    rid = target["rid"]
                    for paper in gold[rid]:
                        pmid = str(paper["pmid"])
                        records = links[rid].get(pmid, [])
                        # Keep the historical first-record rule for paper-level comparison. Retain all rows for audit.
                        first = records[0] if records else {"side": "none", "verbatim": False}
                        rows.append(dict(rid=rid, pmid=pmid, gold=paper["finding"], sys=first["side"],
                                         none_reason=paper.get("none_reason"), verbatim=first["verbatim"], records=records))
                measures = scoring._measures(rows)
                pack_report[arm] = {"measures": measures, "pairs": rows}
                print(pack, arm, measures)
    write_json(args.out / ("results.json" if client is not None else "plan.json"), report)


if __name__ == "__main__":
    main()
