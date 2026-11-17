"""The method against later systematic reviews (specs/whole-system/review-gold-2026-11-17.yaml): for every usable link of
Argon packs 29 and 30 (intervention -> main outcome -> population, labelled by the review's pooled result), a card built by
code, the working search and reader as of T, and the rules of the manual; then the AUC of the outcome link's strength S
against the label, beside a plain count of records.

    python -m scripts.whole_system.review_gold run --fake            # free: the mechanics on the fake LLM
    ALLOW_PAID=1 MAX_USD=3.5 python -m scripts.whole_system.review_gold run [--packs 29] [--limit N]   # paid, resumable
    python -m scripts.whole_system.review_gold score [--packs 29]   # free

Results in longevity-kg reviews/argon-2026-11-17/review_gold_run.json (private: records carry quotes from abstracts).
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

KG = Path(__file__).resolve().parents[2].parent / "longevity-kg"
DIR = KG / "reviews" / "argon-2026-11-17"
OUT = DIR / "review_gold_run.json"
CONFIG = "configs/v3-flash-n10.yaml"
KIND = {"drug": "compound", "supplement": "compound", "exercise": "exercise", "nutrition": "diet", "behavioural": "behavioural",
        "device": "device", "procedure": "procedure", "organisation_of_care": "other", "other": "other"}


def links(packs: list[int]) -> list[dict]:
    """Usable links: the review included, its label valid, its result quote verbatim, T set with studies on both sides."""
    out = []
    for pack in packs:
        f = DIR / f"pack_{pack}_check.json"
        if not f.exists():
            continue
        rows = {r["pmid"]: r for r in json.loads(f.read_text())["rows"]}
        smp = json.loads((DIR / f"pack_{pack}_sample.json").read_text())
        ans = {}
        for i in range(1, smp.get("parts", 3) + 1):
            g = DIR / f"pack_{pack}_{i}_answer.json"
            if g.exists():
                ans.update({str(r["pmid"]): r for r in json.loads(g.read_text())["reviews"]})
        for p, r in rows.items():
            if r.get("include") and r.get("usable") and r.get("label") in ("benefit", "no_effect", "harm") \
                    and r["quotes"]["result_quote"] == "whole":
                a = ans[p]
                out.append({"review": p, "pack": pack, "T": r["T"], "label": r["label"], "certainty": a.get("certainty"),
                            **{k: a.get(k, "") for k in ("intervention", "comparator", "outcome", "population", "intervention_kind")}})
    return out


def card_of(link: dict):
    from hyparena.card.models import HypothesisCard
    iv, out, pop, comp = link["intervention"], link["outcome"], link["population"], link["comparator"]
    claim_plain = f"{iv} improves {out} in {pop}, compared with {comp}."
    return HypothesisCard.model_validate({
        "id": f"RG{link['review']}", "raw_id": link["review"], "hypothesis_type": "interventional", "claim_plain": claim_plain,
        "pico": {"population": {"taxon": "NCBITaxon:9606", "label": "human", "condition": pop, "span": pop},
                 "intervention": [{"type": KIND.get(link.get("intervention_kind") or "other", "other"), "label": iv, "span": iv}],
                 "comparator": {"type": "unknown", "label": comp or "unknown", "span": comp},
                 "outcome": {"metric": out, "direction": "unknown", "span": out}},
        "claims": [{"id": "c1", "subject": {"label": iv}, "relation": "improves_healthspan_in", "object": {"label": "human"},
                    "qualifiers": {"species": "human", "disease": pop, "comparator": comp, "measure": out},
                    "role": "outcome", "link": "outcome", "source_span": claim_plain, "primary": True, "part": "chain"}],
        "main_factor": {"label": iv, "kind": "intervention", "span": iv}})


def run(packs: list[int], fake: bool = False, limit: int | None = None, max_calls: int = 2000) -> dict:
    import yaml
    from hyparena.pipeline import _client
    from hyparena.reading import verifier as vf
    from hyparena.reports.usage import summarize
    from hyparena.scoring import rules_v3 as r3, rules_v32 as r32
    cfg = yaml.safe_load(Path(CONFIG).read_text())
    vf.READ_BATCH = int(cfg.get("read_batch") or 0)
    from hyparena.scoring import rules as _rules
    _rules.GRADED_CONTEXT = cfg.get("admission") == "graded"
    out_f = OUT.with_name(OUT.stem + ("_fake" if fake else "") + ".json")
    done = json.loads(out_f.read_text()) if out_f.exists() else {}
    client, fams = _client(CONFIG, fake, max_calls)
    todo = [l for l in links(packs) if l["review"] not in done][:limit]
    for l in todo:
        card = card_of(l)
        log: list = []
        try:
            ver = vf.verify(client, ["deepseek"] if "deepseek" in fams else fams[:1], "unknown", card, as_of=l["T"], log=log,
                            search=cfg.get("search", "filtered"), template_version=cfg.get("verify_version", ""), probes=False)
            e = r32.evaluate(card, ver.claims, {}, v36=True)
            cv = ver.claims[0]
            S, lo, hi, F, A = e.links["c1"]
            res = {"S": S, "F": F, "A": A, "gate": e.gate, "records_for": len(cv.evidence), "records_against": len(cv.counterevidence),
                   "read": len({p for x in log if x.get("kind") == "search" for p in x.get("pmids", [])}),
                   "usage": summarize(log), "verification": ver.model_dump(mode="json")}
        except Exception as ex:                       # a failing link is recorded, not retried silently
            res = {"error": f"{type(ex).__name__}: {ex}"[:500]}
        done[l["review"]] = {"link": l, **res}
        out_f.write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n")
    return {"links": len(links(packs)), "done": len(done), "errors": sum("error" in v for v in done.values()),
            "usd": round(sum(((v.get("usage") or {}).get("total") or {}).get("usd") or 0 for v in done.values()), 3)}


def auc(vals: list[tuple[float, int]]) -> float | None:
    pos, neg = [v for v, l in vals if l == 1], [v for v, l in vals if l == 0]
    if not pos or not neg:
        return None
    return round(sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg)), 3)


def boot(vals: list[tuple[float, int]], n: int = 2000) -> list[float] | None:
    rng, out = random.Random(0), []
    for _ in range(n):
        s = [rng.choice(vals) for _ in vals]
        a = auc(s)
        if a is not None:
            out.append(a)
    out.sort()
    return [out[int(0.025 * len(out))], out[int(0.975 * len(out)) - 1]] if out else None


def score(packs: list[int], fake: bool = False) -> dict:
    done = json.loads(OUT.with_name(OUT.stem + ("_fake" if fake else "") + ".json").read_text())
    rows = [v for v in done.values() if "error" not in v and v["link"]["pack"] in packs]
    lab = lambda v: int(v["link"]["label"] == "benefit")
    with_records = [v for v in rows if v["records_for"] + v["records_against"] > 0]
    S = [(v["S"], lab(v)) for v in with_records]
    count = [(v["records_for"] - v["records_against"], lab(v)) for v in with_records]
    firm = [(v["S"], lab(v)) for v in with_records if v["link"].get("certainty") in ("moderate", "high")]
    res = {"links": len(rows), "errors": sum("error" in v for v in done.values()),
           "with_records": len(with_records), "share_with_records": round(len(with_records) / len(rows), 3) if rows else None,
           "labels": {"benefit": sum(lab(v) for v in rows), "other": sum(1 - lab(v) for v in rows)},
           "auc_S": auc(S), "ci95_S": boot(S), "auc_count": auc(count), "ci95_count": boot(count),
           "auc_S_moderate_high": auc(firm), "n_moderate_high": len(firm),
           "records_per_link_median": sorted(v["records_for"] + v["records_against"] for v in rows)[len(rows) // 2] if rows else None,
           "usd": round(sum(((v.get("usage") or {}).get("total") or {}).get("usd") or 0 for v in done.values()), 3)}
    (DIR / ("review_gold_score" + ("_fake" if fake else "") + ".json")).write_text(json.dumps(res, indent=1) + "\n")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["run", "score"])
    ap.add_argument("--packs", type=int, nargs="+", default=[29])
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    out = run(a.packs, a.fake, a.limit) if a.cmd == "run" else score(a.packs, a.fake)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
