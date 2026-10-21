"""Checks of the normalizer and the verifier against the worked examples of the card spec (tests/fixtures/cards),
on real models (paid: ALLOW_PAID=1). Stage 1 and 2 of the calibration plan.

    python -m hyparena.card.check_examples normalize --families google,deepseek --repeats 3 --out runs/stage1
    python -m hyparena.card.check_examples verify --family deepseek --repeats 2 --out runs/stage2

The normalizer runs on the raw texts and is compared with the hand-written declared layers: the card validates,
the admission decision, hypothesis type, the outcome relation and organism, the claim relations, inheritance
marks, the contrast of Example 3, `measure` on organism relations. The verifier runs on the reference cards (so
only the verifier varies) and is compared with the reference statuses and evidence profile; the literature is
today's, so a difference is a finding to read, not automatically an error."""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import yaml

from hyparena.card import alternatives, entities
from hyparena.card.models import HypothesisCard, Verification
from hyparena.card.normalizer import normalize
from hyparena.card.rules import admit, finalize, validate_card
from hyparena.card.verifier import verify
from hyparena.llm.providers import build_client

FIX = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "cards"
EXAMPLES = ["ex1_rapamycin_healthspan", "ex2_senolytics_function", "ex3_rapamycin_mechanism", "ex5_resveratrol_endpoint"]


def load(name: str) -> dict:
    return yaml.safe_load((FIX / f"{name}.yaml").read_text(encoding="utf-8"))


def texts() -> list[dict]:
    """Raw texts with the reference card (when one exists) and the expected admission."""
    out = [{"name": n, "raw": load(n)["raw"], "card": load(n)["card"], "admission": load(n)["expected"]["admission"]}
           for n in EXAMPLES]
    for case in load("ex4_admission")["cases"]:
        out.append({"name": case["name"], "raw": case["raw"], "card": case.get("card") if case["expected"]["decision"] == "accepted" else None,
                    "admission": case["expected"]["decision"]})
    return out


def _sig(c) -> tuple:
    return (c.relation, c.role)


def compare_card(got: HypothesisCard, ref: dict | None, raw: str, admission_expected: str) -> dict:
    out = {"problems": validate_card(got, raw), "admission": admit(got).decision}
    out["admission_ok"] = out["admission"] == admission_expected
    if ref is None:
        return out
    r = HypothesisCard.model_validate(ref)
    ro, go = r.outcome_claim, got.outcome_claim
    out["type_ok"] = got.hypothesis_type == r.hypothesis_type
    out["outcome_relation_ok"] = bool(go and ro and go.relation == ro.relation)
    out["outcome"] = f"{go.relation} {go.object.label}" if go else None
    want, have = Counter(map(_sig, r.claims)), Counter(map(_sig, got.claims))
    out["claims"] = {"reference": len(r.claims), "got": len(got.claims),
                     "matched (relation, role)": sum((want & have).values())}
    out["inheritance_ok"] = sorted(sorted(c.inherited_from_pico) for c in got.claims if c.inherited_from_pico) == \
        sorted(sorted(c.inherited_from_pico) for c in r.claims if c.inherited_from_pico)
    if r.rejected_alternatives:
        ga = got.rejected_alternatives
        out["contrast_ok"] = bool(ga) and bool(go) and go.qualifiers.get("contrast") == ga[0].id and \
            ga[0].relation == r.rejected_alternatives[0].relation
    org = [c for c in got.claims if c.relation in ("slows_aging_in", "improves_healthspan_in")]
    out["measure_ok"] = all(c.qualifiers.get("measure") or c.relation == "improves_healthspan_in" for c in org)
    return out


def run_normalize(families: list[str], repeats: int, out_dir: Path, config: str, max_calls: int) -> dict:
    client, _, _ = build_client(config, max_calls=max_calls, families=families)
    rows = []
    for fam in families:
        for rep in range(repeats):
            for t in texts():
                log: list = []
                started = time.time()
                card, problems = normalize(client, fam, t["raw"], "H-0001", log=log)
                row = {"family": fam, "repeat": rep, "name": t["name"], "seconds": round(time.time() - started, 1),
                       "calls": sum(1 for x in log if x.get("kind") == "llm"), "normalizer_problems": problems}
                if card is not None:
                    entities.resolve_card(card)
                    row.update(compare_card(card, t["card"], t["raw"], t["admission"]))
                    row["card"] = card.model_dump(by_alias=True)
                rows.append(row)
                print(json.dumps({k: v for k, v in row.items() if k != "card"}, ensure_ascii=False), flush=True)
    return _save(out_dir, "normalize", rows, client)


def run_verify(family: str, repeats: int, out_dir: Path, config: str, max_calls: int) -> dict:
    client, pool, _ = build_client(config, max_calls=max_calls)
    spare = [j.family for j in pool if j.family != family]
    rows = []
    for rep in range(repeats):
        for name in EXAMPLES:
            d = load(name)
            card = HypothesisCard.model_validate(d["card"])
            entities.resolve_card(card)
            log: list = []
            ver = finalize(card, verify(client, [family], "unknown", card, log=log, fallback_families=spare))
            if ver.evidence_profile.gate == "pass":
                alternatives.check(client, family, card, ver, log=log)
            exp = d["expected"]
            prof = ver.evidence_profile.model_dump(by_alias=True)
            got_st = {cv.id: cv.status for cv in ver.claims}
            row = {"repeat": rep, "name": name, "calls": sum(1 for x in log if x.get("kind") == "llm"),
                   "statuses": got_st, "statuses_expected": exp["statuses"],
                   "status_diff": {k: [got_st.get(k), v] for k, v in exp["statuses"].items() if got_st.get(k) != v},
                   "profile_diff": {k: [prof.get(k), v] for k, v in exp["profile"].items() if prof.get(k) != v},
                   "records": [{"claim": cv.id, "side": side, "pmid": r.record_id, "role": r.quote_role, "sex": r.sex,
                                "strain": r.strain, "dose": r.dose, "human_rungs": r.human_rungs,
                                "qm": r.qualifiers_match, "quote": r.quote[:160]}
                               for cv in ver.claims for side, rs in (("for", cv.evidence), ("against", cv.counterevidence))
                               for r in rs],
                   "refusals": [{"claim": cv.id, "type": r.type, "pmid": r.record_id} for cv in ver.claims for r in cv.refusals],
                   "alternatives": [{"id": a.id, "type": a.type, "status": a.status, "pmid": a.record_id}
                                    for a in ver.alternatives],
                   "searched": len(ver.searched_pmids)}
            rows.append(row)
            print(json.dumps({k: row[k] for k in ("repeat", "name", "calls", "status_diff", "profile_diff")},
                             ensure_ascii=False), flush=True)
            (out_dir / f"verify_{name}_{rep}.json").parent.mkdir(parents=True, exist_ok=True)
            (out_dir / f"verify_{name}_{rep}.json").write_text(
                json.dumps({"verification": ver.model_dump(by_alias=True), "calls": log}, ensure_ascii=False, indent=1, default=str))
    return _save(out_dir, "verify", rows, client)


def _save(out_dir: Path, kind: str, rows: list, client) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    res = {"kind": kind, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "calls": client.calls,
           "failures": client.failures, "rows": rows}
    (out_dir / f"{kind}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(f"calls {client.calls}, failures {client.failures}")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("normalize")
    n.add_argument("--families", default="google,deepseek")
    v = sub.add_parser("verify")
    v.add_argument("--family", default="deepseek")
    for p in (n, v):
        p.add_argument("--repeats", type=int, default=2)
        p.add_argument("--out", required=True)
        p.add_argument("--config", default="configs/v2-flash.yaml")
        p.add_argument("--max-calls", type=int, default=150)
    a = ap.parse_args()
    if a.cmd == "normalize":
        run_normalize(a.families.split(","), a.repeats, Path(a.out), a.config, a.max_calls)
    else:
        run_verify(a.family, a.repeats, Path(a.out), a.config, a.max_calls)


if __name__ == "__main__":
    main()
