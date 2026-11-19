"""Prepare and check an offline pilot for preserving article-level outcomes on the existing reader call."""
from __future__ import annotations

import argparse
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from hyparena.card.models import HypothesisCard
from hyparena.llm.prompts import render
from hyparena.reading.verifier import _norm, _validate, claim_endpoint, outcome_label, parse_records


EXTRA = """
In the same JSON object, add "paper_outcomes": an array with up to two observations per supplied PMID.
Each item is {"source_pmid": "", "measure": "", "excerpt": ""}. Keep the existing papers and records unchanged.
Save directly measured human function or an animal behavioral or functional test from the paper's own results,
even if the result addresses a different claim. Use the exact words of the abstract for the measure and one
contiguous excerpt that names it and reports what was observed. Include nonpositive results.
Omit mentions in background, planned endpoints, molecular markers and results of other studies mentioned in passing.
If the abstract has no such result, leave the array empty. This array does not support or refute the current claim.
""".strip()


def repair_measure(measure: str, excerpt: str, abstract: str) -> str | None:
    """Recover a source span from a measure with one extra leading word."""
    words = measure.split()
    if len(words) < 3 or not words[0].isalpha() or words[0].lower() in {"no", "not", "without"}:
        return None
    whole = r"(?<!\w)" + re.escape(_norm(measure)) + r"(?!\w)"
    if not re.search(whole, _norm(abstract)):
        return None
    suffix = re.findall(r"\w+", " ".join(words[1:]).lower())
    generic = {"the", "a", "an", "of", "in", "by", "and", "or", "rate", "score", "mean", "percent", "change"}
    if len([word for word in suffix if word not in generic]) < 2:
        return None
    pattern = r"(?<!\w)" + r"\s+".join(re.escape(word) for word in words[1:]) + r"(?!\w)"
    match = re.search(pattern, excerpt, re.IGNORECASE)
    return match.group() if match else None


def validated_outcomes(value, abstracts, *, repair=False):
    rows, issues, seen, counts = [], [], set(), {}
    items = value.get("paper_outcomes", [])
    if not isinstance(items, list):
        return rows, ["paper_outcomes must be a list"]
    for item in items:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("source_pmid", "measure", "excerpt")):
            issues.append("invalid shape")
            continue
        pmid, measure, quote = item["source_pmid"], _norm(item["measure"]), _norm(item["excerpt"])
        if pmid not in abstracts:
            issues.append("wrong PMID")
        elif not quote or quote not in _norm(abstracts[pmid]["abstract"]):
            issues.append("unverified quote")
        else:
            if not measure or measure not in quote:
                fixed = repair_measure(item["measure"], item["excerpt"], abstracts[pmid]["abstract"]) if repair else None
                if fixed is None:
                    issues.append("measure missing from quote")
                    continue
                item = {**item, "measure": fixed, "original_measure": item["measure"],
                        "repair": "dropped_leading_word"}
                measure = _norm(fixed)
            # Equal measures can be observed in different comparisons.
            key = (pmid, measure, quote) if repair else (pmid, measure)
            if key in seen:
                issues.append("duplicate measure")
            elif counts.get(pmid, 0) >= 2:
                issues.append("too many outcomes")
            else:
                rows.append(item)
                seen.add(key)
                counts[pmid] = counts.get(pmid, 0) + 1
    return rows, issues


def check_contract():
    source = {"1": {"abstract": "We measured gait speed. Walking speed declined after discharge."}}
    valid = {"source_pmid": "1", "measure": "Walking speed", "excerpt": "Walking speed declined after discharge."}
    attempts = [valid, dict(valid, source_pmid="2"), dict(valid, excerpt="Walking speed improved after discharge."),
                dict(valid, excerpt="We measured gait speed. Walking speed declined."),
                dict(valid, measure="grip strength"), valid]
    rows, errors = validated_outcomes({"paper_outcomes": attempts}, source)
    assert rows == [valid]
    assert errors == ["wrong PMID", "unverified quote", "unverified quote", "measure missing from quote", "duplicate measure"]
    record = {"pmid": "1", "quote": "We measured gait speed."}
    truncated = '{"records": [' + json.dumps(record) + '], "paper_outcomes": [' + json.dumps(valid) + ','
    assert parse_records(truncated) == {"records": [record], "truncated": True}
    return len(attempts) + 1


def load(path):
    return json.loads(path.read_text())


def replay_repair(work, replies):
    cases = {r["id"]: r for r in work["cases"]}
    results = []
    for reply in replies:
        if reply["arm"] != "candidate":
            continue
        case = cases[reply["id"]]
        source = {case["pmid"]: case["abstract"]}
        raw = reply["reply"] or {}
        original, issues = validated_outcomes(raw, source)
        assert original == reply["outcomes"] and issues == reply["outcome_issues"]
        repaired, new_issues = validated_outcomes(raw, source, repair=True)
        results.append({"id": case["id"], "original": original, "repaired": repaired,
                        "original_issues": issues, "remaining_issues": new_issues})
    return results


def pubmed_xml(path):
    abstracts = {}
    for article in ET.parse(path).findall(".//PubmedArticle"):
        text = lambda x: "".join(x.itertext())
        pmid = article.findtext(".//MedlineCitation/PMID")
        abstracts[pmid] = {
            "pmid": pmid, "title": text(article.find(".//ArticleTitle")),
            "year": article.findtext(".//JournalIssue/PubDate/Year") or "",
            "abstract": " ".join(text(x) for x in article.findall(".//Abstract/AbstractText")),
            "review": any((x.text or "").lower().endswith("review") for x in article.findall(".//PublicationType")),
        }
    return abstracts


def prepare(root, xml):
    archive = root / "evaluation"
    ref = load(root / "feedback-2026-11-18/novelty-comparisons-2026-11-19.json")
    dossier = load(archive / "dossier.json")
    abstracts = pubmed_xml(xml)
    cases = []
    for case in load(archive / "cases.json"):
        ident = case["id"]
        pmid = ref[ident]["pmid"]
        paper = abstracts[pmid]
        records = [(v["id"], r) for v in case["verifications"] for field in ("evidence", "counterevidence", "no_stance")
                   for r in v.get(field, []) if r["record_id"].removeprefix("PMID:") == pmid]
        claim_id = records[0][0]
        card = HypothesisCard.model_validate(case["card"])
        c = next(c for c in card.claims if c.id == claim_id)
        p = card.pico
        endpoint = claim_endpoint(c)
        variables = {
            "claim": c, "claim_plain": card.claim_plain, "outcome_label": outcome_label(c), "endpoint": endpoint,
            "human_healthspan": endpoint == "healthspan" and c.qualifiers.get("species", "").lower() == "human",
            "negated": False, "alternative": False, "competitor": False, "contrast": "", "history_text": "",
            "qualifiers": ", ".join(f"{k}: {v}" for k, v in c.qualifiers.items() if v and v != "unknown"),
            "population": ", ".join(f"{k} {v}" for k, v in p.population.model_dump().items() if v and v != "unknown"),
            "intervention": "; ".join(f"{i.label} ({i.regimen}, {i.route})" for i in p.intervention),
            "comparator": p.comparator.label, "abstracts": [paper],
        }
        base = render("verify_claim", "v21", **variables)
        gold = [
            {"measure": o["endpoint"], "quote": f["text"]}
            for s in dossier["sources"] if str(s["source"]["pmid"]) == pmid
            for o in s["observations"] if o["endpoint_type"] == "functional"
            for f in o["source_fragments"]
            if _norm(f.get("text")) and _norm(f["text"]) in _norm(paper["abstract"])
        ]
        cases.append({"id": ident, "pmid": pmid, "link": claim_id, "abstract": paper,
                      "prompts": {"v21": base, "candidate": base + "\n\n" + EXTRA},
                      "reference_outcomes": gold,
                      "original_measures": [r["outcome_measure"] for _, r in records if r.get("outcome_measure")]})
    return {"offline_checks": check_contract(), "cases": cases}


def run(work, out):
    from hyparena.pipeline import _client

    if os.environ.get("ALLOW_PAID") != "1" or not 0 < float(os.environ.get("MAX_USD", "0")) <= .07:
        raise SystemExit("Requires approved ALLOW_PAID=1 and a MAX_USD limit of at most 0.07.")
    if out.exists():
        raise SystemExit("Output already exists; choose a new path and check previous charges.")
    client, families = _client("configs/v3-flash-n10.yaml", False, 20)
    if "deepseek" not in families:
        raise SystemExit("The frozen reader family is unavailable.")
    client.retries = 0
    client.fallback_families = []
    saved = []
    for case in work["cases"]:
        abstracts = {case["pmid"]: case["abstract"]}
        for arm, prompt in case["prompts"].items():
            now = datetime.now(timezone.utc)
            if now.weekday() < 5 and (1 <= now.hour < 4 or 6 <= now.hour < 10):
                raise SystemExit("Stopped before a call in the provider's peak pricing window.")
            reply = client.call(role="verify_claim", family="deepseek", prompt=prompt)
            value = parse_records(reply.text)
            rows, issues = validated_outcomes(value or {}, abstracts)
            saved.append({"id": case["id"], "arm": arm, "outcomes": rows, "outcome_issues": issues,
                          "link_issues": _validate(value, abstracts) if value else ["missing parsed reply"],
                          "reply": value, "error": reply.error, "tokens_in": reply.tokens_in,
                          "tokens_out": reply.tokens_out, "total_usd": client.usd})
            out.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    cmds = p.add_subparsers(dest="action", required=True)
    prep = cmds.add_parser("prepare")
    for flag in ("root", "pubmed-xml", "out"):
        prep.add_argument(f"--{flag}", type=Path, required=True)
    paid = cmds.add_parser("run")
    for flag in ("work", "out"):
        paid.add_argument(f"--{flag}", type=Path, required=True)
    replay = cmds.add_parser("replay")
    for flag in ("work", "replies", "out"):
        replay.add_argument(f"--{flag}", type=Path, required=True)
    args = p.parse_args()
    if args.action == "prepare":
        args.out.write_text(json.dumps(prepare(args.root, args.pubmed_xml), ensure_ascii=False, indent=2) + "\n")
    elif args.action == "replay":
        args.out.write_text(json.dumps(replay_repair(load(args.work), load(args.replies)), ensure_ascii=False, indent=2) + "\n")
    else:
        run(load(args.work), args.out)


if __name__ == "__main__":
    main()
